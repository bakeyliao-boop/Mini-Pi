"""D07：真实模型适配器；generate 核心逻辑由学习者敲入。"""

import asyncio
import os
from collections.abc import Sequence
from copy import deepcopy
from time import perf_counter
from urllib.parse import urlsplit

from mini_pi.async_http_transport import post_json_async
from mini_pi.http_transport import post_json
from mini_pi.models import ConversationItem, Message, ToolDefinition
from mini_pi.qwen_provider import build_request, parse_assistant_message
from mini_pi.thread_worker import run_sync_with_cleanup


class QwenProvider:
    """配置与发送记录由辅助代码准备，对外实现统一的 generate 接口。"""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "qwen3.8-flash",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout: float = 30.0,
        max_requests: int = 4,
        max_completion_tokens: int = 1024,
    ):
        key = api_key if api_key is not None else os.getenv("DASHSCOPE_API_KEY")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("未配置 DASHSCOPE_API_KEY；请在本地环境变量中设置密钥")
        if "\r" in key or "\n" in key:
            raise ValueError("API Key 中不能包含换行符")
        address = urlsplit(base_url)
        if (
            address.scheme != "https"
            or not address.hostname
            or address.username
            or address.password
            or address.query
            or address.fragment
        ):
            raise ValueError("base_url 必须是无认证信息、查询参数和片段的 HTTPS 地址")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("模型 ID 必须是非空字符串")
        if timeout <= 0 or max_requests <= 0 or max_completion_tokens <= 0:
            raise ValueError("超时、请求次数和输出上限必须大于零")
        self._api_key = key
        self.model = model
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self.timeout = timeout
        self.max_requests = max_requests
        self.max_completion_tokens = max_completion_tokens
        self.request_count = 0
        self.request_records: list[dict] = []

    async def _send(self, request: dict) -> dict:
        """发送请求，记录耗时和服务原始 usage，不保存凭证。"""
        if self.request_count >= self.max_requests:
            raise RuntimeError("已达到本次适配器的请求次数上限，停止继续请求")
        self.request_count += 1
        payload = deepcopy(request)
        payload["enable_thinking"] = False
        payload["max_completion_tokens"] = self.max_completion_tokens
        record = {
            "request": self.request_count,
            "requested_model": self.model,
            "request_body": deepcopy(payload),
            "returned_model": None,
            "finish_reason": None,
            "usage": None,
            "status": "requesting",
        }
        started = perf_counter()
        try:
            response = await post_json_async(
                self.endpoint,self._api_key,payload,self.timeout
                )
            # response = await run_sync_with_cleanup(
            #     post_json, self.endpoint, self._api_key, payload, self.timeout
            # )
            # response = await asyncio.to_thread(
            #     post_json, self.endpoint, self._api_key, payload, self.timeout
            # )
            record["returned_model"] = response.get("model")
            record["usage"] = deepcopy(response.get("usage"))
            choices = response.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                record["finish_reason"] = choices[0].get("finish_reason")
            record["status"] = "received"
            return response
        except asyncio.CancelledError:
            record["status"] = "cancelled"
            raise
        except Exception:
            record["status"] = "request_error"
            raise
        finally:
            record["elapsed_seconds"] = round(perf_counter() - started, 6)
            self.request_records.append(record)

    async def generate(
        self,
        history: Sequence[ConversationItem],
        tools: Sequence[ToolDefinition],
    ) -> Message:
        """组装请求、等待响应、检查结束原因，再返回统一 Message。"""
        # 在这里敲入本步骤的核心代码。
        request = build_request(self.model, history, tools)
        response = await self._send(request)

        choice = response["choices"][0]
        if choice["finish_reason"] not in ("stop", "tool_calls"):
            raise ValueError("模型响应未正常完成，不执行其中的调用")

        return parse_assistant_message(choice["message"])
