"""助手准备：只验向量数学与模型规格，不调用真实 embedding 或搜索。"""

from dataclasses import FrozenInstanceError
import math
import unittest

from mini_pi.memory.embedding import (
    EmbeddingSpec,
    cosine_similarity,
    unit_vector,
)
from mini_pi.memory.errors import MemoryEmbeddingError


class MemoryVectorTests(unittest.TestCase):
    def test_spec_keeps_model_revision_and_dimensions_frozen(self):
        spec = EmbeddingSpec("local-test-model", "revision-1", 2)
        self.assertEqual(("local-test-model", "revision-1", 2), (
            spec.model_id, spec.revision, spec.dimensions,
        ))
        self.assertEqual(spec, EmbeddingSpec("local-test-model", "revision-1", 2))
        self.assertNotEqual(spec, EmbeddingSpec("other-model", "revision-1", 2))
        self.assertNotEqual(spec, EmbeddingSpec("local-test-model", "revision-2", 2))
        self.assertNotEqual(spec, EmbeddingSpec("local-test-model", "revision-1", 3))
        with self.assertRaises(FrozenInstanceError):
            spec.dimensions = 3

    def test_spec_rejects_empty_identifiers_and_non_positive_integer_dimensions(self):
        for field in ("model_id", "revision"):
            for value in ("", " \t\n", None, 123, True):
                arguments = {"model_id": "model", "revision": "v1", "dimensions": 2}
                arguments[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(MemoryEmbeddingError):
                        EmbeddingSpec(**arguments)
        for dimensions in (0, -1, True, False, 2.0, "2", None):
            with self.subTest(dimensions=dimensions):
                with self.assertRaises(MemoryEmbeddingError):
                    EmbeddingSpec("model", "v1", dimensions)

    def test_unit_vector_returns_float_tuple_without_mutating_input(self):
        vector = [3, 4]
        normalized = unit_vector(vector, 2)
        self.assertIsInstance(normalized, tuple)
        self.assertTrue(all(isinstance(value, float) for value in normalized))
        self.assertAlmostEqual(0.6, normalized[0])
        self.assertAlmostEqual(0.8, normalized[1])
        self.assertAlmostEqual(1.0, math.hypot(*normalized))
        self.assertEqual([3, 4], vector)
        vector[0] = 99
        self.assertAlmostEqual(0.6, normalized[0])

    def test_cosine_distinguishes_same_orthogonal_and_opposite_directions(self):
        for document, expected in (([7, 0], 1.0), ([0, 5], 0.0), ([-9, 0], -1.0)):
            with self.subTest(document=document):
                score = cosine_similarity([2, 0], document, 2)
                self.assertAlmostEqual(expected, score)
                self.assertGreaterEqual(score, -1.0)
                self.assertLessEqual(score, 1.0)

    def test_cosine_normalizes_both_inputs_without_mutation(self):
        query = [3, 4]
        document = [40, 30]
        self.assertAlmostEqual(0.96, cosine_similarity(query, document, 2))
        self.assertAlmostEqual(0.96, cosine_similarity(document, query, 2))
        self.assertEqual([3, 4], query)
        self.assertEqual([40, 30], document)

    def test_unit_vector_is_idempotent_at_similarity_threshold_boundary(self):
        normalized = unit_vector([3, 4], 2)
        self.assertEqual(normalized, (0.6, 0.8))
        self.assertEqual(unit_vector(normalized, 2), normalized)
        score = cosine_similarity((1.0, 0.0), normalized, 2)
        self.assertEqual(score, 0.6)
        self.assertGreaterEqual(score, 0.6)

    def test_helpers_reject_invalid_dimensions_instead_of_coercing_them(self):
        for dimensions in (0, -2, True, False, 2.0, "2", None):
            with self.subTest(dimensions=dimensions):
                with self.assertRaises(MemoryEmbeddingError):
                    unit_vector([1, 0], dimensions)
                with self.assertRaises(MemoryEmbeddingError):
                    cosine_similarity([1, 0], [1, 0], dimensions)

    def test_helpers_reject_empty_and_wrong_dimension_vectors_on_both_sides(self):
        for vector in ([], [1], [1, 0, 0]):
            with self.subTest(vector=vector):
                with self.assertRaises(MemoryEmbeddingError):
                    unit_vector(vector, 2)
                with self.assertRaises(MemoryEmbeddingError):
                    cosine_similarity(vector, [1, 0], 2)
                with self.assertRaises(MemoryEmbeddingError):
                    cosine_similarity([1, 0], vector, 2)

    def test_helpers_reject_invalid_components_and_zero_vectors_on_both_sides(self):
        for vector in (
            [True, 0], [False, 1], ["1", 0], [None, 0], [object(), 0],
            [math.nan, 1], [math.inf, 1], [-math.inf, 1], [0, 0],
        ):
            with self.subTest(vector=vector):
                with self.assertRaises(MemoryEmbeddingError):
                    unit_vector(vector, 2)
                with self.assertRaises(MemoryEmbeddingError):
                    cosine_similarity(vector, [1, 0], 2)
                with self.assertRaises(MemoryEmbeddingError):
                    cosine_similarity([1, 0], vector, 2)

    def test_finite_large_and_small_nonzero_vectors_can_be_normalized(self):
        for scale in (1e308, 1e-308):
            with self.subTest(scale=scale):
                normalized = unit_vector([scale, scale], 2)
                self.assertTrue(all(math.isfinite(value) for value in normalized))
                self.assertAlmostEqual(1.0, math.hypot(*normalized))
                self.assertAlmostEqual(1.0, cosine_similarity(
                    [scale, scale], [1, 1], 2,
                ))


if __name__ == "__main__":
    unittest.main()
