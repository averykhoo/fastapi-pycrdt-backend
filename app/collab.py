from anyio import Lock
from fastapi import WebSocket, WebSocketDisconnect
from pycrdt import Channel
from pycrdt.websocket import WebsocketServer, exception_logger


class FastAPIWebsocket(Channel):
    """Adapts a FastAPI/Starlette WebSocket to the Channel protocol that
    pycrdt.websocket.WebsocketServer.serve() expects."""

    def __init__(self, websocket: WebSocket, path: str):
        self._websocket = websocket
        self._path = path
        self._send_lock = Lock()

    @property
    def path(self) -> str:
        return self._path

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        try:
            return await self.recv()
        except (WebSocketDisconnect, RuntimeError):
            raise StopAsyncIteration()

    async def send(self, message: bytes) -> None:
        async with self._send_lock:
            await self._websocket.send_bytes(message)

    async def recv(self) -> bytes:
        return bytes(await self._websocket.receive_bytes())


websocket_server = WebsocketServer(exception_handler=exception_logger)
