"""助手准备：阿里 embedding 辅助层离线反例；不读取真实凭据或调用模型。"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import io
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mini_pi.memory.dashscope_embedding import (
    DashScopeEmbedder,
    checked_texts,
    parse_embedding_response,
)
from mini_pi.memory.embedding import EmbeddingSpec
from mini_pi.memory.errors import MemoryEmbeddingError


def response_with(*items):
    return {"output": {"embeddings": list(items)}}


def embedding_item(index, vector):
    return {"text_index": index, "embedding": vector}


class CheckedEmbeddingTextsTests(unittest.TestCase):
    def test_preserves_original_text_and_rejects_partial_invalid_batches(self):
        texts = ["  依赖下载失败？\n", "文档\t正文"]
        self.assertEqual(tuple(texts), checked_texts(texts))
        self.assertEqual(["  依赖下载失败？\n", "文档\t正文"], texts)
        for invalid in ("", " \n\t", None, 7, True, b"text"):
            for invalid_index in (0, 1):
                batch = ["查询", "文档"]
                batch[invalid_index] = invalid
                with self.subTest(invalid=invalid, invalid_index=invalid_index):
                    with self.assertRaises(MemoryEmbeddingError):
                        checked_texts(batch)

    def test_a_single_string_is_not_a_batch_and_empty_requires_explicit_permission(self):
        for invalid in ("两个字", b"text", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(MemoryEmbeddingError):
                    checked_texts(invalid)
        with self.assertRaises(MemoryEmbeddingError):
            checked_texts([])
        self.assertEqual((), checked_texts([], allow_empty=True))
        with self.assertRaises(MemoryEmbeddingError):
            checked_texts([" "], allow_empty=True)

    def test_batch_limit_rejects_extra_input_instead_of_truncating(self):
        texts = ["一", "二", "三"]
        self.assertEqual(tuple(texts), checked_texts(texts, max_count=3))
        with self.assertRaises(MemoryEmbeddingError):
            checked_texts(texts, max_count=2)


class DashScopeResponseTests(unittest.TestCase):
    def test_out_of_order_results_are_restored_by_text_index_and_normalized(self):
        response = response_with(
            embedding_item(2, [-9, 0]),
            embedding_item(0, [3, 4]),
            embedding_item(1, [0, -8]),
        )
        original = copy.deepcopy(response)

        vectors = parse_embedding_response(response, expected_count=3, dimensions=2)

        self.assertIsInstance(vectors, tuple)
        for actual, expected in zip(
            vectors, ((0.6, 0.8), (0.0, -1.0), (-1.0, 0.0)), strict=True,
        ):
            self.assertIsInstance(actual, tuple)
            self.assertTrue(all(type(number) is float for number in actual))
            self.assertAlmostEqual(1.0, math.hypot(*actual))
            for number, expected_number in zip(actual, expected, strict=True):
                self.assertAlmostEqual(expected_number, number)
        self.assertEqual(original, response)
        response["output"]["embeddings"][1]["embedding"][0] = 999
        self.assertAlmostEqual(0.6, vectors[0][0])

    def test_missing_or_extra_results_never_return_a_partial_batch(self):
        for items in (
            (),
            (embedding_item(0, [1, 0]),),
            tuple(embedding_item(index, [1, 0]) for index in range(3)),
        ):
            with self.subTest(items=items):
                with self.assertRaises(MemoryEmbeddingError):
                    parse_embedding_response(response_with(*items), 2, 2)

    def test_indexes_must_be_unique_in_range_actual_integers(self):
        for invalid_index in (True, False, 0.0, "0", None, -1, 2):
            response = response_with(
                embedding_item(invalid_index, [1, 0]),
                embedding_item(1, [0, 1]),
            )
            with self.subTest(invalid_index=invalid_index):
                with self.assertRaises(MemoryEmbeddingError):
                    parse_embedding_response(response, 2, 2)
        with self.assertRaises(MemoryEmbeddingError):
            parse_embedding_response(
                response_with(embedding_item(0, [1, 0]), embedding_item(0, [0, 1])),
                2, 2,
            )

    def test_response_shape_and_required_item_fields_are_validated(self):
        for invalid in (
            None, [], "response", {}, {"output": None}, {"output": []},
            {"output": {}}, {"output": {"embeddings": None}},
            {"output": {"embeddings": {"0": [1, 0]}}},
            {"output": {"embeddings": "10"}},
            response_with(None), response_with([]), response_with({}),
            response_with({"embedding": [1, 0]}),
            response_with({"text_index": 0}),
        ):
            with self.subTest(response=invalid):
                with self.assertRaises(MemoryEmbeddingError):
                    parse_embedding_response(invalid, 1, 2)

    def test_invalid_vector_anywhere_rejects_the_entire_response(self):
        for invalid in (
            [], [1], [1, 0, 0], [0, 0], [math.nan, 1], [math.inf, 1],
            [-math.inf, 1], [True, 0], ["1", 0], [10**400, 1], None, "10",
        ):
            for invalid_index in (0, 1):
                items = [embedding_item(0, [1, 0]), embedding_item(1, [0, 1])]
                items[invalid_index]["embedding"] = invalid
                with self.subTest(invalid=invalid, invalid_index=invalid_index):
                    with self.assertRaises(MemoryEmbeddingError):
                        parse_embedding_response(response_with(*items), 2, 2)

    def test_service_failure_wins_even_when_output_looks_valid_and_message_is_private(self):
        private_message = "synthetic-service-message-do-not-echo"
        for failure in (
            {"error": None}, {"error": {"message": private_message}},
            {"code": "InvalidApiKey"}, {"code": 0}, {"code": False},
        ):
            response = response_with(embedding_item(0, [1, 0]))
            response.update(failure)
            response["message"] = private_message
            output = io.StringIO()
            with self.subTest(failure=failure):
                with redirect_stdout(output), redirect_stderr(output):
                    with self.assertRaises(MemoryEmbeddingError) as raised:
                        parse_embedding_response(response, 1, 2)
                self.assertNotIn(private_message, str(raised.exception))
                self.assertNotIn(private_message, repr(raised.exception))
                self.assertNotIn(private_message, output.getvalue())
        for success_code in (None, ""):
            response = response_with(embedding_item(0, [3, 4]))
            response["code"] = success_code
            with self.subTest(success_code=success_code):
                self.assertEqual(((0.6, 0.8),), parse_embedding_response(response, 1, 2))

    def test_parser_rejects_invalid_expected_count_or_dimensions(self):
        response = response_with(embedding_item(0, [1, 0]))
        for count in (0, -1, True, False, 1.0, "1", None):
            with self.subTest(expected_count=count):
                with self.assertRaises(MemoryEmbeddingError):
                    parse_embedding_response(response, count, 2)
        for dimensions in (0, -1, True, False, 2.0, "2", None):
            with self.subTest(dimensions=dimensions):
                with self.assertRaises(MemoryEmbeddingError):
                    parse_embedding_response(response, 1, dimensions)


class DashScopeConfigurationTests(unittest.TestCase):
    def test_construction_declares_vector_space_and_endpoint_is_read_only(self):
        embedder = DashScopeEmbedder("synthetic-key", dimensions=128)
        self.assertEqual(
            EmbeddingSpec("text-embedding-v4", "dashscope-native-query-document-v1", 128),
            embedder.spec,
        )
        endpoint = embedder.endpoint
        self.assertTrue(endpoint.startswith("https://dashscope.aliyuncs.com/api/v1/"))
        with self.assertRaises(AttributeError):
            embedder.endpoint = "https://other.invalid/api/v1"
        self.assertEqual(endpoint, embedder.endpoint)

    def test_bad_configuration_fails_before_any_request_can_start(self):
        cases = [
            {"api_key": key} for key in ("", " \t", "synthetic\nkey", "synthetic\rkey", None)
        ]
        cases += [{"model": model} for model in ("text-embedding-v3", "", None)]
        cases += [
            {"dimensions": dimensions}
            for dimensions in (0, 63, 129, True, False, 64.0, "64", None)
        ]
        cases += [
            {"timeout": timeout}
            for timeout in (0, -1, True, False, math.nan, math.inf, -math.inf, "30", None)
        ]
        cases += [
            {"base_url": base_url} for base_url in (
                "http://example.invalid/api/v1", "https://example.invalid/compatible-mode/v1",
                "https://user:password@example.invalid/api/v1",
                "https://example.invalid/api/v1?token=synthetic",
                "https://example.invalid/api/v1#fragment", "https:///api/v1", "", None,
            )
        ]
        with mock.patch("socket.socket", side_effect=AssertionError("unexpected network")):
            for change in cases:
                arguments = {"api_key": "synthetic-key"}
                arguments.update(change)
                with self.subTest(configuration=change):
                    with self.assertRaises(MemoryEmbeddingError):
                        DashScopeEmbedder(**arguments)

    def test_all_supported_dimensions_are_accepted_without_opening_a_socket(self):
        with mock.patch("socket.socket", side_effect=AssertionError("unexpected network")):
            for dimensions in (64, 128, 256, 512, 768, 1024, 1536, 2048):
                with self.subTest(dimensions=dimensions):
                    self.assertEqual(
                        dimensions, DashScopeEmbedder("synthetic-key", dimensions=dimensions).spec.dimensions,
                    )

    def test_explicit_file_handles_bom_comments_and_quotes_without_mutating_environment(self):
        content = (
            "  # synthetic configuration only\n\n"
            " MEMORY_EMBEDDING_API_KEY = 'synthetic-file-key' \n"
            ' MEMORY_EMBEDDING_MODEL = "text-embedding-v4"\n'
            " MEMORY_EMBEDDING_DIMENSIONS = '128' \n"
            ' MEMORY_EMBEDDING_BASE_URL = "https://file.invalid/api/v1" \n'
            " UNRELATED_APPLICATION_SETTING = '${IGNORED_VALUE}'\n"
            " MEMORY_EMBEDDING_TIMEOUT = definitely-not-a-number\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(content, encoding="utf-8-sig")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("socket.socket", side_effect=AssertionError("unexpected network")):
                    embedder = DashScopeEmbedder.from_env(env_file, timeout=4.5)
                self.assertEqual(128, embedder.spec.dimensions)
                self.assertTrue(embedder.endpoint.startswith("https://file.invalid/api/v1/"))
                self.assertEqual({}, dict(os.environ))

    def test_environment_overrides_each_file_setting_including_an_invalid_file_key_and_model(self):
        content = (
            "MEMORY_EMBEDDING_API_KEY=\n"
            "MEMORY_EMBEDDING_MODEL=unsupported-file-model\n"
            "MEMORY_EMBEDDING_DIMENSIONS=128\n"
            "MEMORY_EMBEDDING_BASE_URL=https://file.invalid/api/v1\n"
        )
        environment = {
            "MEMORY_EMBEDDING_API_KEY": "synthetic-environment-key",
            "MEMORY_EMBEDDING_MODEL": "text-embedding-v4",
            "MEMORY_EMBEDDING_DIMENSIONS": "256",
            "MEMORY_EMBEDDING_BASE_URL": "https://environment.invalid/api/v1",
        }
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(content, encoding="utf-8")
            with mock.patch.dict(os.environ, environment, clear=True):
                embedder = DashScopeEmbedder.from_env(env_file)
                self.assertEqual(256, embedder.spec.dimensions)
                self.assertTrue(embedder.endpoint.startswith("https://environment.invalid/api/v1/"))
                self.assertEqual(environment, dict(os.environ))

    def test_invalid_environment_values_do_not_fall_back_to_valid_file_values(self):
        content = (
            "MEMORY_EMBEDDING_API_KEY=synthetic-file-key\n"
            "MEMORY_EMBEDDING_MODEL=text-embedding-v4\n"
            "MEMORY_EMBEDDING_DIMENSIONS=128\n"
            "MEMORY_EMBEDDING_BASE_URL=https://file.invalid/api/v1\n"
        )
        changes = (
            {"MEMORY_EMBEDDING_API_KEY": ""},
            {"MEMORY_EMBEDDING_API_KEY": "synthetic\nkey"},
            {"MEMORY_EMBEDDING_MODEL": "text-embedding-v3"},
            {"MEMORY_EMBEDDING_DIMENSIONS": "True"},
            {"MEMORY_EMBEDDING_DIMENSIONS": "128.0"},
            {"MEMORY_EMBEDDING_BASE_URL": "http://environment.invalid/api/v1"},
        )
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(content, encoding="utf-8")
            for change in changes:
                with self.subTest(environment=change):
                    with mock.patch.dict(os.environ, change, clear=True):
                        with self.assertRaises(MemoryEmbeddingError):
                            DashScopeEmbedder.from_env(env_file)

    def test_file_values_are_not_expanded_and_unrelated_keys_are_not_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "MEMORY_EMBEDDING_API_KEY=synthetic-key\n"
                'MEMORY_EMBEDDING_MODEL="${SYNTHETIC_MODEL}"\n',
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SYNTHETIC_MODEL": "text-embedding-v4"}, clear=True):
                with self.assertRaises(MemoryEmbeddingError):
                    DashScopeEmbedder.from_env(env_file)
            env_file.write_text("DASHSCOPE_API_KEY=synthetic-unrelated-key\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"DASHSCOPE_API_KEY": "synthetic-unrelated-key"}, clear=True):
                with self.assertRaises(MemoryEmbeddingError):
                    DashScopeEmbedder.from_env(env_file)

    def test_without_an_explicit_file_loading_uses_only_the_supplied_environment(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(
                os.environ, {"MEMORY_EMBEDDING_API_KEY": "synthetic-environment-key"}, clear=True,
            ))
            stack.enter_context(mock.patch.object(
                Path, "read_text", side_effect=AssertionError("unexpected implicit file read"),
            ))
            stack.enter_context(mock.patch("socket.socket", side_effect=AssertionError("unexpected network")))
            embedder = DashScopeEmbedder.from_env()
            self.assertEqual(1024, embedder.spec.dimensions)
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MemoryEmbeddingError):
                DashScopeEmbedder.from_env()

    def test_missing_explicit_file_is_a_configuration_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(MemoryEmbeddingError):
                    DashScopeEmbedder.from_env(Path(directory) / "missing.env")


if __name__ == "__main__":
    unittest.main()
