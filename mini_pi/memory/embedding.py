"""助手准备：embedding 端口与向量格式/数学辅助，不执行召回决策。

此文件不绑定供应商、不联网、不读取凭证、不缓存向量。
规格由实际适配器声明；模型和配置一致性还须在检索编排中核对。
"""

from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Protocol

from mini_pi.memory.errors import MemoryEmbeddingError


@dataclass(frozen=True)
class EmbeddingSpec:
    """固定向量空间的声明；revision 应包含适配器的模型/预处理配置版本。"""

    model_id: str
    revision: str
    dimensions: int

    def __post_init__(self):
        for name in ("model_id", "revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise MemoryEmbeddingError(f"{name} 必须是非空字符串")
        if type(self.dimensions) is not int or self.dimensions < 1:
            raise MemoryEmbeddingError("dimensions 必须是正整数，不能使用布尔值")


class Embedder(Protocol):
    """真实适配器与固定测试替身共用的接口；不是一个 embedding 模型实现。

    查询和文档可由模型要求使用不同前缀，但必须处于同一兼容向量空间。
    文档返回的第 i 个向量必须对应 texts[i]；实际适配器须核对服务索引，
    拒绝缺项或重复索引，并按输入顺序还原，不允许静默错配。
    async 方法需要将取消传到实际请求并完成关闭；本端口本身不提供此保证。
    """

    @property
    def spec(self) -> EmbeddingSpec: ...

    async def embed_query(self, text: str) -> Sequence[float]: ...

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


def unit_vector(vector: Sequence[float], dimensions: int) -> tuple[float, ...]:
    """核验并归一化一个非零向量，拒绝错误表示，不修改输入。"""
    if type(dimensions) is not int or dimensions < 1:
        raise MemoryEmbeddingError("向量维度必须是正整数")
    if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes, bytearray)):
        raise MemoryEmbeddingError("向量必须是数值序列")
    if len(vector) != dimensions:
        raise MemoryEmbeddingError("向量维度与固定模型规格不一致")
    values = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MemoryEmbeddingError("向量元素必须是有限数值，不能使用布尔值")
        try:
            number = float(value)
        except (ValueError, OverflowError) as error:
            raise MemoryEmbeddingError("向量元素不能安全表示为浮点数") from error
        if not math.isfinite(number):
            raise MemoryEmbeddingError("向量不能包含 NaN 或无穷大")
        values.append(number)
    # 已单位化时保持原值，避免再次缩放/除法引入额外舍入并误跨阈值边界。
    if math.hypot(*values) == 1.0:
        return tuple(values)
    # 先缩放再求范数，避免有限大数在平方/求和时溢出。
    scale = max(abs(value) for value in values)
    if scale == 0:
        raise MemoryEmbeddingError("零向量不能用于余弦相似度")
    scaled = [value / scale for value in values]
    norm = math.hypot(*scaled)
    return tuple(value / norm for value in scaled)


def normalize_document_vectors(
    vectors: Sequence[Sequence[float]], expected_count: int, dimensions: int,
) -> tuple[tuple[float, ...], ...]:
    """核对非空批次的数量、每条向量并保持对应顺序，不返回部分结果。

    这里只验证格式，不能从数值证明每条向量确实属于对应文本。
    文本与返回索引的对应关系由适配器保证并另行测试。
    """
    if type(expected_count) is not int or expected_count < 1:
        raise MemoryEmbeddingError("候选批次数量必须是正整数")
    if not isinstance(vectors, Sequence) or isinstance(vectors, (str, bytes, bytearray)):
        raise MemoryEmbeddingError("候选向量批次必须是向量序列")
    if len(vectors) != expected_count:
        raise MemoryEmbeddingError("候选向量数量与原文数量不一致")
    return tuple(unit_vector(vector, dimensions) for vector in vectors)


def cosine_similarity(
    query: Sequence[float], document: Sequence[float], dimensions: int,
) -> float:
    """计算兼容向量的余弦值；不判断范围、适用性、阈值或返回数量。"""
    left = unit_vector(query, dimensions)
    right = unit_vector(document, dimensions)
    score = math.fsum(a * b for a, b in zip(left, right, strict=True))
    # 仅修正浮点舍入导致的微小越界，不构造业务相关性分数。
    return max(-1.0, min(1.0, score))
