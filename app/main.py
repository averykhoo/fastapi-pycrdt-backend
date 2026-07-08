from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from app.collab import FastAPIWebsocket, websocket_server


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with websocket_server:
        yield


app = FastAPI(title="fastapi-pycrdt-backend", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.websocket("/room/{doc_id}")
async def collab_room(websocket: WebSocket, doc_id: str) -> None:
    await websocket.accept()
    await websocket_server.serve(FastAPIWebsocket(websocket, doc_id))


app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)
