"""Wires pycrdt-websocket's room/server machinery into FastAPI.

pycrdt-websocket ships a transport-agnostic `WebsocketServer` that expects to
be fed objects implementing its `Channel` protocol (an async iterator of
`bytes` with `.path`, `.send()`, `.recv()`). `FastAPIWebsocket` is that
adapter for a Starlette/FastAPI `WebSocket`. `PersistentWebsocketServer`
layers SQLite-backed persistence on top so a room's document survives a
server restart.
"""

from anyio import Lock
from fastapi import WebSocket, WebSocketDisconnect
from pycrdt import Channel
from pycrdt.store import SQLiteYStore, YDocNotFound
from pycrdt.websocket import WebsocketServer, YRoom, exception_logger

from app.config import settings


class FastAPIWebsocket(Channel):
    """Adapts a FastAPI/Starlette `WebSocket` to the `Channel` protocol that
    `pycrdt.websocket.WebsocketServer.serve()` expects.

    Args:
        websocket: An already-`accept()`-ed Starlette websocket connection.
        path: The room name this connection belongs to (used by
            `WebsocketServer` to route the client to the right `YRoom`).
    """

    def __init__(self, websocket: WebSocket, path: str) -> None:
        self._websocket = websocket
        self._path = path
        self._send_lock = Lock()

    @property
    def path(self) -> str:
        """The room name this channel is connected to."""
        return self._path

    def __aiter__(self) -> "FastAPIWebsocket":
        return self

    async def __anext__(self) -> bytes:
        """Yield the next inbound message, or stop iteration on disconnect."""
        try:
            return await self.recv()
        except (WebSocketDisconnect, RuntimeError):
            raise StopAsyncIteration()

    async def send(self, message: bytes) -> None:
        """Send a raw Yjs sync/awareness message to this client.

        Serialized with a lock because pycrdt-websocket may schedule
        concurrent sends (e.g. broadcast fan-out) onto the same channel, and
        a Starlette `WebSocket` is not safe for concurrent `send_bytes` calls.
        """
        async with self._send_lock:
            await self._websocket.send_bytes(message)

    async def recv(self) -> bytes:
        """Block for the next raw message sent by this client."""
        return bytes(await self._websocket.receive_bytes())


class AppYStore(SQLiteYStore):
    """`SQLiteYStore` pinned to this app's configured database path.

    All rooms share one SQLite file; `SQLiteYStore` distinguishes their
    update logs internally by the `path` passed to its constructor (the room
    name), so this subclass only needs to fix `db_path`.
    """

    db_path = str(settings.ystore_path)


class PersistentWebsocketServer(WebsocketServer):
    """A `WebsocketServer` whose rooms are backed by a SQLite `YStore`.

    Stored update history is replayed into the room's `ydoc` while the room
    is still marked not-ready — a room only starts observing (and therefore
    re-persisting) document updates once `ready` is set, so replaying past
    updates here does not write them back to the store a second time.
    """

    async def get_room(self, name: str) -> YRoom:
        """Return the `YRoom` for `name`, creating and hydrating it from the
        `YStore` on first access.

        Args:
            name: The room name (matches the CRDT-doc-id/websocket path).

        Returns:
            The running `YRoom`, ready to accept the caller's client.
        """
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
                pass  # no prior history for this room — start from a blank doc
            room.ready = True
        room = self.rooms[name]
        await self.start_room(room)
        return room


# Singleton shared by the FastAPI app's lifespan (started/stopped alongside
# it) and every websocket route handler.
websocket_server = PersistentWebsocketServer(exception_handler=exception_logger)
