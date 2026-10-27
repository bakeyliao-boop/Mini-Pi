"""助手准备：自然语言向量查询的格式门禁，不调用模型或搜索。"""

import math
import unittest

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryScope
from mini_pi.memory.retrieval_helpers import normalize_vector_search_request


class VectorSearchInputTests(unittest.TestCase):
    def call(self, **changes):
        args = dict(scope=MemoryScope('A', 'Pi'), conditions=(),
                    at='2026-10-22T18:00:00+08:00', query='依赖包为什么下载失败？',
                    top_k=3, min_score=0.2)
        args.update(changes)
        return normalize_vector_search_request(**args)

    def test_preserves_natural_language_and_normalizes_only_conditions_and_time(self):
        query = ' 请解释依赖下载失败的原因；保留上下文。 '
        self.assertEqual(self.call(query=query, conditions=(('tz', 'Asia/Shanghai'), ('day', 'weekday'))),
            ((('day', 'weekday'), ('tz', 'Asia/Shanghai')),
             '2026-10-22T10:00:00.000000+00:00', query, 3, 0.2))

    def test_invalid_query_and_top_k_are_rejected(self):
        for query in ('', ' \n', None, 1, ('依赖',)):
            with self.subTest(query=query), self.assertRaises(MemoryPolicyError):
                self.call(query=query)
        for top_k in (0, -1, True, False, 3.0, '3', None):
            with self.subTest(top_k=top_k), self.assertRaises(MemoryPolicyError):
                self.call(top_k=top_k)

    def test_threshold_is_finite_in_range_and_not_boolean(self):
        for threshold in (-1, 0, 1, 0.25):
            with self.subTest(threshold=threshold):
                self.assertEqual(self.call(min_score=threshold)[-1], float(threshold))
        for threshold in (-1.01, 1.01, math.nan, math.inf, -math.inf, True, '0.2', None, 10**400):
            with self.subTest(threshold=threshold), self.assertRaises(MemoryPolicyError):
                self.call(min_score=threshold)

    def test_invalid_scope_time_and_conditions_are_rejected(self):
        for change in [dict(scope=MemoryScope('', 'Pi')), dict(at='2026-10-22'),
                       dict(conditions=(('day', 'a'), ('day', 'b'))), dict(conditions=[])]:
            with self.subTest(change=change), self.assertRaises(MemoryPolicyError):
                self.call(**change)


if __name__ == '__main__':
    unittest.main()
