from anyio import Lock
from fastapi import WebSocket, WebSocketDisconnect
from pycrdt import Channel
from pycrdt.store import SQLiteYStore, YDocNotFound
from pycrdt.websocket import WebsocketServer, YRoom, exception_logger

from app.config import settings


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


class AppYStore(SQLiteYStore):
    db_path = str(settings.ystore_path)


class PersistentWebsocketServer(WebsocketServer):
    """Rooms backed by a SQLite YStore. Stored history is replayed into the
    room's ydoc while the room is still not ready — the room only starts
    observing (and thus re-persisting) doc updates once ready is set."""

    async def get_room(self, name: str) -> YRoom:
        if name not in self.rooms:
            ystore = AppYStore(path=name)
            room = YRoom(
                ready=False,
                ystore=ystore,
                exception_handler=self.exception_handler,
                log=self.log,
            )
            self.rooms[name] = room
            await self.start_room(room)
            await ystore.started.wait()
            try:
                await ystore.apply_updates(room.ydoc)
            except YDocNotFound:
                pass
            room.ready = True
        room = self.rooms[name]
        await self.start_room(room)
        return room


websocket_server = PersistentWebsocketServer(exception_handler=exception_logger)
