"""MEM-03：阿里原生 embedding 适配骨架，核心调用由学习者分段手敲。

助手准备配置、输入/响应格式校验及 HTTP 记录；不读取 Session、不决定召回。
from_env 只有显式传 env_file 才读文件，构造对象不联网。
"""

import asyncio
from collections.abc import Sequence
import math
import os
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

from mini_pi.async_http_transport import post_json_async
from mini_pi.memory.embedding import EmbeddingSpec, unit_vector
from mini_pi.memory.errors import MemoryEmbeddingError


BATCH_SIZE = 10
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
_SETTING_KEYS = (
    "MEMORY_EMBEDDING_API_KEY", "MEMORY_EMBEDDING_MODEL",
    "MEMORY_EMBEDDING_DIMENSIONS", "MEMORY_EMBEDDING_BASE_URL",
)


def checked_texts(
    texts: Sequence[str], *, allow_empty: bool = False, max_count: int | None = None,
) -> tuple[str, ...]:
    """保留完整原文并取快照；不猜 token 数，不截断超长输入。"""
    if not isinstance(texts, Sequence) or isinstance(texts, (str, bytes, bytearray)):
        raise MemoryEmbeddingError("embedding 输入必须是文本序列")
    result = tuple(texts)
    if not result and not allow_empty:
        raise MemoryEmbeddingError("embedding 批次不能为空")
    if max_count is not None and len(result) > max_count:
        raise MemoryEmbeddingError("embedding 单批文本数量超过模型上限")
    if any(not isinstance(text, str) or not text.strip() for text in result):
        raise MemoryEmbeddingError("embedding 每条输入必须是非空文本")
    return result


def parse_embedding_response(
    response: dict, expected_count: int, dimensions: int,
) -> tuple[tuple[float, ...], ...]:
    """验证 native 响应并依 text_index 复原输入顺序；拒绝部分结果。"""
    if type(expected_count) is not int or expected_count < 1:
        raise MemoryEmbeddingError("预期向量数量必须为正整数")
    if not isinstance(response, dict):
        raise MemoryEmbeddingError("embedding 响应必须是对象")
    if (
        "error" in response or response.get("code") not in (None, "")
        or ("status_code" in response and response["status_code"] not in (200, "200"))
    ):
        raise MemoryEmbeddingError("embedding 服务返回失败；未自动重试")
    output = response.get("output")
    items = output.get("embeddings") if isinstance(output, dict) else None
    if not isinstance(items, list) or len(items) != expected_count:
        raise MemoryEmbeddingError("embedding 响应缺少完整向量批次")
    by_index = {}
    for item in items:
        if not isinstance(item, dict):
            raise MemoryEmbeddingError("embedding 向量条目必须是对象")
        index = item.get("text_index")
        if type(index) is not int or not 0 <= index < expected_count or index in by_index:
            raise MemoryEmbeddingError("embedding 返回索引缺失、重复或越界")
        by_index[index] = unit_vector(item.get("embedding"), dimensions)
    return tuple(by_index[index] for index in range(expected_count))


def _read_embedding_settings(env_file: str | Path | None) -> dict[str, str]:
    """仅解析本项目简单 KEY=value；支持外层配对引号，不求值或变量展开。"""
    settings = {}
    if env_file is not None:
        try:
            lines = Path(env_file).read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError):
            raise MemoryEmbeddingError("无法读取指定的本地 embedding 配置文件") from None
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.partition("=")
            name = name.strip()
            if not separator or name not in _SETTING_KEYS:
                continue
            if name in settings:
                raise MemoryEmbeddingError("本地 embedding 配置含重复字段")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            settings[name] = value
    for name in _SETTING_KEYS:
        if name in os.environ:
            settings[name] = os.environ[name]
    return settings


class DashScopeEmbedder:
    """首版仅支持 text-embedding-v4；不缓存、不重试、不记录凭据或原文。"""

    def __init__(
        self, api_key: str, *, model: str = "text-embedding-v4", dimensions: int = 1024,
        base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0,
    ):
        if not isinstance(api_key, str) or not api_key.strip() or "\r" in api_key or "\n" in api_key:
            raise MemoryEmbeddingError("请配置有效的 MEMORY_EMBEDDING_API_KEY")
        if model != "text-embedding-v4":
            raise MemoryEmbeddingError("当前适配器仅支持 text-embedding-v4")
        if type(dimensions) is not int or dimensions not in (64, 128, 256, 512, 768, 1024, 1536, 2048):
            raise MemoryEmbeddingError("向量维度不在 text-embedding-v4 支持范围内")
        if not isinstance(base_url, str):
            raise MemoryEmbeddingError("embedding base_url 必须是原生 HTTPS 接口地址")
        try:
            address = urlsplit(base_url)
            port = address.port
        except ValueError:
            raise MemoryEmbeddingError("embedding base_url 格式错误") from None
        if (
            address.scheme != "https" or not address.hostname or address.username or address.password
            or address.query or address.fragment or address.path.rstrip("/") != "/api/v1"
            or any(character.isspace() for character in base_url)
        ):
            raise MemoryEmbeddingError("embedding base_url 必须是无认证、查询和片段的 HTTPS /api/v1 地址")
        try:
            valid_timeout = not isinstance(timeout, bool) and isinstance(timeout, (int, float)) and math.isfinite(timeout) and timeout > 0
        except OverflowError:
            valid_timeout = False
        if not valid_timeout:
            raise MemoryEmbeddingError("embedding timeout 必须是有限正数")
        self._api_key = api_key
        self._endpoint = base_url.rstrip("/") + "/services/embeddings/text-embedding/text-embedding"
        self._timeout = float(timeout)
        # revision 描述本地协议/预处理，不保证供应商权重版本被固定。
        self._spec = EmbeddingSpec(model, "dashscope-native-query-document-v1", dimensions)
        self.request_records: list[dict] = []

    @classmethod
    def from_env(cls, env_file: str | Path | None = None, *, timeout: float = 30.0):
        """环境变量优先；如需读取工作区 .env，调用时显式传入路径。"""
        settings = _read_embedding_settings(env_file)
        try:
            dimensions = int(settings.get("MEMORY_EMBEDDING_DIMENSIONS", "1024"))
        except ValueError:
            raise MemoryEmbeddingError("MEMORY_EMBEDDING_DIMENSIONS 必须为整数") from None
        return cls(
            settings.get("MEMORY_EMBEDDING_API_KEY", ""),
            model=settings.get("MEMORY_EMBEDDING_MODEL", "text-embedding-v4"),
            dimensions=dimensions,
            base_url=settings.get("MEMORY_EMBEDDING_BASE_URL", DEFAULT_BASE_URL),
            timeout=timeout,
        )

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    @property
    def endpoint(self) -> str:
        return self._endpoint

    async def _send_batch(self, payload: dict, count: int, text_type: str):
        """助手准备：实际 HTTP、无原文计量记录和响应校验；先关闭再向上传播。"""
        record = {
            "model": self.spec.model_id, "dimensions": self.spec.dimensions,
            "text_type": text_type, "text_count": count,
            "request_id": None, "total_tokens": None, "status": "requesting",
        }
        started = perf_counter()
        try:
            response = await post_json_async(self.endpoint, self._api_key, payload, self._timeout)
            # 缺少 usage 就保留 None；已收到响应但格式失败也可能已产生费用。
            usage = response.get("usage")
            tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
            if type(tokens) is int and tokens >= 0:
                record["total_tokens"] = tokens
            request_id = response.get("request_id")
            if isinstance(request_id, str) and request_id:
                record["request_id"] = request_id
            vectors = parse_embedding_response(response, count, self.spec.dimensions)
            record["status"] = "validated"
            return vectors
        except asyncio.CancelledError:
            record["status"] = "cancelled"
            raise
        except Exception:
            record["status"] = "error"
            raise
        finally:
            record["elapsed_seconds"] = perf_counter() - started
            self.request_records.append(record)

    async def _embed_batch(self, texts: Sequence[str], text_type: str):
        """学习者第1段：一个批次的模式、请求体和实际调用。"""
        texts = checked_texts(texts, max_count=BATCH_SIZE)
        if text_type not in ("query", "document"):
            raise MemoryEmbeddingError("text_type 必须为 query 或 document")
        payload = {
            "model":self.spec.model_id,
            "input":{"texts":list(texts)},
            "parameters":{
                "text_type":text_type,
                "dimension":self.spec.dimensions,
                "output_type":"dense",
                },
        }
        return await self._send_batch(payload, len(texts), text_type)

    async def embed_query(self, text: str) -> tuple[float, ...]:
        """学习者第2段：将一个问题编码为一个向量。"""
        vectors = await self._embed_batch([text],"query")
        return vectors[0]

    async def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """学习者第3段：正文按模型上限分批，全部成功才返回。"""
        texts = checked_texts(texts,allow_empty=True)
        vectors = []
        for start in range(0,len(texts),BATCH_SIZE):
            batch = texts[start:start + BATCH_SIZE]
            batch_vectors = await self._embed_batch(batch,"document")
            vectors.extend(batch_vectors)
        return tuple(vectors)
