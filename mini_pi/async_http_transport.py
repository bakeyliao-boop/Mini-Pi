"""D12：可取消的异步 JSON POST；不在线程里等待同步 HTTP。

本次请求独占客户端，成功、失败和取消均关闭响应及客户端。
取消只通知请求任务一次，随后等待其 finally 收尾；重复取消不打断收尾。
当前不复用跨请求连接，会增加建连开销；未来可由 Agent 生命周期管理共享客户端。
"""

import asyncio
import json
from urllib.parse import urlsplit

import httpx


MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _make_client(timeout: float) -> httpx.AsyncClient:
    """客户端由本次请求持有；保留默认 TLS 验证及环境代理行为。"""
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


async def _request_and_close(url: str, api_key: str, data: bytes, timeout: float) -> dict:
    client = _make_client(timeout)
    response = None
    try:
        request = client.build_request(
            "POST", url, content=data,
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        )
        response = await client.send(request, stream=True)
        if not 200 <= response.status_code < 300:
            raise RuntimeError(
                f"模型请求失败：HTTP {response.status_code}；请核对凭证、地域、模型权限及额度"
            )
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                raise RuntimeError("模型响应超过本地大小限制")
            body.extend(chunk)
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise RuntimeError("模型服务没有返回有效的 UTF-8 JSON 响应") from None
        if not isinstance(result, dict):
            raise RuntimeError("模型服务的 JSON 响应必须是对象")
        return result
    except (httpx.HTTPError, TimeoutError, OSError):
        raise RuntimeError("模型请求连接失败或超时；本次未自动重试") from None
    finally:
        # 取消期间这段仍会执行。请求任务只收到一次取消，后续外层取消由等待层吸收。
        try:
            try:
                if response is not None:
                    await response.aclose()
            finally:
                await client.aclose()
        except Exception:
            raise RuntimeError("模型请求客户端清理失败") from None


async def _capture_request(*args):
    """封装普通异常，避免取消竞争时出现未消费的后台异常日志。"""
    try:
        return await _request_and_close(*args), None
    except Exception as error:
        return None, error


async def post_json_async(url: str, api_key: str, payload: dict, timeout: float = 30.0) -> dict:
    """与旧 post_json 相同的输入/JSON 输出；外部取消原样传播，连接先完成收尾。"""
    address = urlsplit(url)
    if address.scheme != "https" or not address.hostname or address.username or address.password:
        raise ValueError("模型请求地址必须是 HTTPS 地址，且不能包含用户名或密码")
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    await asyncio.sleep(0)  # 已到达的取消可在创建客户端前生效。
    request_task = asyncio.create_task(
        _capture_request(url, api_key, data, timeout), name="mini-pi-http-request",
    )
    try:
        value, error = await asyncio.shield(request_task)
        if error is not None:
            raise error
        return value
    except asyncio.CancelledError:
        # 这里取消的是异步请求任务；与 to_thread 不同，取消能进入正在等待的网络操作。
        request_task.cancel()
        while not request_task.done():
            try:
                await asyncio.shield(request_task)
            except asyncio.CancelledError:
                pass
        if not request_task.cancelled():
            _, error = request_task.result()
            if error is not None:
                raise error  # 清理失败等错误不得伪装成已完成的取消。
        raise
