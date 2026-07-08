from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pycrdt import Array
from pydantic import BaseModel

from app.collab import FastAPIWebsocket, websocket_server
from app.db import Document, get_document, init_db, list_documents, register_document


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    async with websocket_server:
        yield


app = FastAPI(title="fastapi-pycrdt-backend", lifespan=lifespan)


class Row(BaseModel):
    start: str = ""
    end: str = ""
    speaker: str = ""
    text: str = ""
    noise: str = ""


class ExportResponse(BaseModel):
    doc_id: str
    rows: list[Row]


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/documents")
def documents() -> list[Document]:
    return list_documents()


@app.get("/api/export/{doc_id}")
async def export_document(doc_id: str) -> ExportResponse:
    document = await run_in_threadpool(get_document, doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="unknown document")
    room = await websocket_server.get_room(doc_id)
    rows = room.ydoc.get("rows", type=Array)
    return ExportResponse(doc_id=doc_id, rows=[Row(**r) for r in rows.to_py()])


@app.websocket("/room/{doc_id}")
async def collab_room(websocket: WebSocket, doc_id: str) -> None:
    await run_in_threadpool(register_document, doc_id)
    await websocket.accept()
    await websocket_server.serve(FastAPIWebsocket(websocket, doc_id))


app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)
