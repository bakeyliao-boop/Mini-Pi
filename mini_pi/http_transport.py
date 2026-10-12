"""D07 的 HTTP 发送辅助代码：使用标准库，不自动重试或输出凭证。"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    """模型请求不跟随重定向，避免将认证头发送到其他地址。"""

    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def post_json(url: str, api_key: str, payload: dict, timeout: float = 30.0) -> dict:
    """POST 一份 JSON，返回响应字典；错误信息不包含认证头或服务原始错误体。"""
    address = urlsplit(url)
    if address.scheme != "https" or not address.hostname or address.username or address.password:
        raise ValueError("模型请求地址必须是 HTTPS 地址，且不能包含用户名或密码")
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(2 * 1024 * 1024 + 1)
    except HTTPError as error:
        status = error.code
        error.close()
        raise RuntimeError(
            f"模型请求失败：HTTP {status}；请核对凭证、地域、模型权限及额度"
        ) from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("模型请求连接失败或超时；本次未自动重试") from None
    if len(body) > 2 * 1024 * 1024:
        raise RuntimeError("模型响应超过本地大小限制")
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise RuntimeError("模型服务没有返回有效的 UTF-8 JSON 响应") from None
    if not isinstance(result, dict):
        raise RuntimeError("模型服务的 JSON 响应必须是对象")
    return result
