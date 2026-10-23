"""助手准备：只验文档向量批次格式，不调用模型或判断文本语义。"""

import math
import unittest

from mini_pi.memory.embedding import normalize_document_vectors
from mini_pi.memory.errors import MemoryEmbeddingError


class MemoryEmbeddingBatchTests(unittest.TestCase):
    def test_batch_keeps_order_normalizes_each_vector_and_preserves_input(self):
        vectors = [[3, 4], [0, -8], [-5, 0]]
        original = [vector.copy() for vector in vectors]

        normalized = normalize_document_vectors(vectors, expected_count=3, dimensions=2)

        self.assertIsInstance(normalized, tuple)
        self.assertEqual(3, len(normalized))
        for actual, expected in zip(
            normalized, ((0.6, 0.8), (0.0, -1.0), (-1.0, 0.0)), strict=True,
        ):
            self.assertIsInstance(actual, tuple)
            self.assertTrue(all(isinstance(value, float) for value in actual))
            self.assertAlmostEqual(1.0, math.hypot(*actual))
            for value, expected_value in zip(actual, expected, strict=True):
                self.assertAlmostEqual(expected_value, value)
        self.assertEqual(original, vectors)
        vectors[0][0] = 99
        self.assertAlmostEqual(0.6, normalized[0][0])
        self.assertEqual(
            ((1.0, 0.0), (0.0, 1.0)),
            normalize_document_vectors(((2, 0), (0, 7)), 2, 2),
        )

    def test_missing_short_or_extra_batch_results_are_errors(self):
        for vectors in ([], [[1, 0]], [[1, 0], [0, 1], [-1, 0]]):
            with self.subTest(vectors=vectors):
                with self.assertRaises(MemoryEmbeddingError):
                    normalize_document_vectors(vectors, expected_count=2, dimensions=2)

    def test_outer_shape_and_expected_count_are_strictly_validated(self):
        for vectors in (
            None, "12", b"12", bytearray(b"12"), 7,
            {0: [1, 0]}, iter([[1, 0]]),
        ):
            with self.subTest(vectors=vectors):
                with self.assertRaises(MemoryEmbeddingError):
                    normalize_document_vectors(vectors, expected_count=1, dimensions=2)
        for expected_count in (0, -1, True, False, 1.0, "1", None):
            with self.subTest(expected_count=expected_count):
                with self.assertRaises(MemoryEmbeddingError):
                    normalize_document_vectors([[1, 0]], expected_count, dimensions=2)

    def test_any_invalid_vector_rejects_the_whole_batch(self):
        for invalid in (
            [math.nan, 1], [math.inf, 1], [-math.inf, 1], [0, 0],
            [], [1], [1, 0, 0], [True, 0], ["1", 0], None, "10",
        ):
            for invalid_index in (0, 1):
                vectors = [[1, 0], [0, 1]]
                vectors[invalid_index] = invalid
                with self.subTest(invalid=invalid, invalid_index=invalid_index):
                    with self.assertRaises(MemoryEmbeddingError):
                        normalize_document_vectors(vectors, expected_count=2, dimensions=2)


if __name__ == "__main__":
    unittest.main()
