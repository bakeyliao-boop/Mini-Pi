"""助手准备：真实本地 HTTPS 服务与客户端资源观察；不访问外部服务。"""

import asyncio
import json
from pathlib import Path
import ssl

import httpx


class LocalHttpsServer:
    def __init__(self, *, mode="normal", status=200, body=None):
        fixtures = Path(__file__).resolve().parent / "fixtures"
        self.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.server_context.load_cert_chain(fixtures / "localhost-cert.pem", fixtures / "localhost-key.pem")
        self.client_context = ssl.create_default_context(cafile=str(fixtures / "localhost-cert.pem"))
        self.mode = mode
        self.status = status
        self.body = body if body is not None else json.dumps({"ok": True}).encode()
        self.started = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.response_seen = asyncio.Event()
        self.requests = []
        self.clients = []
        self.responses = []
        self.handlers = set()
        self.writers = set()
        self.errors = []
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(
            self._handle, "127.0.0.1", 0, ssl=self.server_context,
            ssl_handshake_timeout=2, ssl_shutdown_timeout=2,
        )
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"https://127.0.0.1:{port}/v1/chat/completions"
        return self

    def make_client(self, timeout):
        async def observe_response(response):
            self.responses.append(response)
            self.response_seen.set()

        client = httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, verify=self.client_context,
            trust_env=False, event_hooks={"response": [observe_response]},
        )
        self.clients.append(client)
        return client

    async def _handle(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        self.writers.add(writer)
        try:
            header_bytes = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            lines = header_bytes.decode("ascii").split("\r\n")
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.lower()] = value.strip()
            body = await asyncio.wait_for(reader.readexactly(int(headers.get("content-length", "0"))), 5)
            self.requests.append({"start": lines[0], "headers": headers, "body": body})
            self.started.set()
            if self.mode != "hang_headers":
                extra = "Location: /redirected\r\n" if self.status == 302 else ""
                writer.write((
                    f"HTTP/1.1 {self.status} Test\r\nContent-Length: {len(self.body)}\r\n"
                    f"Content-Type: application/json\r\n{extra}Connection: close\r\n\r\n"
                ).encode("ascii"))
                writer.write(self.body[:1] if self.mode == "hang_body" else self.body)
                await writer.drain()
            if self.mode in {"hang_headers", "hang_body"}:
                # 服务保持不回复，不由测试放行；客户端取消须使服务器实际观察到断开。
                await asyncio.wait_for(reader.read(), 6)
                self.disconnected.set()
        except (ConnectionError, ssl.SSLError, asyncio.IncompleteReadError):
            self.disconnected.set()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.errors.append(type(error).__name__)
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (ConnectionError, ssl.SSLError, TimeoutError):
                writer.transport.abort()
            self.writers.discard(writer)
            self.handlers.discard(task)

    async def close(self):
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        for writer in list(self.writers):
            writer.transport.abort()
        handlers = list(self.handlers)
        if handlers:
            done, pending = await asyncio.wait(handlers, timeout=2)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
