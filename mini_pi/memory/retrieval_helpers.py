"""助手准备：读取请求的格式检查，不决定一条记忆是否适用。"""

import math

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import Conditions, MemoryScope
from mini_pi.memory.validation_helpers import (
    normalize_conditions, normalize_time, require_text,
)


def normalize_read_request(
    scope: MemoryScope, conditions: Conditions, at: str,
) -> tuple[Conditions, str]:
    """规范化可信调用方给定的场景条件和问题时间，不创建数据库。"""
    if not isinstance(scope, MemoryScope):
        raise MemoryPolicyError("scope 必须是 MemoryScope")
    require_text(scope.user_id, "user_id")
    require_text(scope.project_id, "project_id")
    return normalize_conditions(conditions), normalize_time(at)


def normalize_search_request(
    scope: MemoryScope, conditions: Conditions, at: str,
    key: str | None, terms: tuple[str, ...], limit: int,
) -> tuple[Conditions, str, str | None, tuple[str, ...], int]:
    """助手准备：只整理查询格式，不读取数据库或筛选/排序候选。

    key 保留精确标识；关键词去首尾空白、忽略大小写并去重。
    禁止空查询；limit 必须为正整数，布尔值不算整数。
    """
    conditions, at = normalize_read_request(scope, conditions, at)
    if key is not None:
        require_text(key, "key")
    if not isinstance(terms, tuple):
        raise MemoryPolicyError("terms 必须是关键词元组")
    for term in terms:
        require_text(term, "关键词")
    terms = tuple(sorted({term.strip().casefold() for term in terms}))
    if key is None and not terms:
        raise MemoryPolicyError("必须提供 key 或关键词")
    if type(limit) is not int or limit < 1:
        raise MemoryPolicyError("limit 必须是正整数，不能使用布尔值")
    return conditions, at, key, terms, limit


def normalize_vector_search_request(
    scope: MemoryScope, conditions: Conditions, at: str,
    query: str, top_k: int, min_score: float,
) -> tuple[Conditions, str, str, int, float]:
    """只校验向量查询参数；不按词拆解问题，不自动选择模型或阈值。"""
    conditions, at = normalize_read_request(scope, conditions, at)
    require_text(query, "query")
    if type(top_k) is not int or top_k < 1:
        raise MemoryPolicyError("top_k 必须是正整数，不能使用布尔值")
    if type(min_score) not in (int, float):
        raise MemoryPolicyError("min_score 必须是 [-1,1] 内有限实数")
    try:
        threshold = float(min_score)
    except (ValueError, OverflowError) as error:
        raise MemoryPolicyError("min_score 不能安全表示为有限实数") from error
    if not math.isfinite(threshold) or not -1 <= threshold <= 1:
        raise MemoryPolicyError("min_score 必须是 [-1,1] 内有限实数")
    return conditions, at, query, top_k, threshold
