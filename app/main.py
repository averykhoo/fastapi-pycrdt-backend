import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response, UploadFile, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pycrdt import Array
from pydantic import BaseModel

from app.activity import ActivityBatch, StatsResponse, compute_stats, record_events
from app.audio import audio_path, get_audio, save_audio
from app.collab import FastAPIWebsocket, websocket_server
from app.db import Document, get_document, init_db, list_documents, register_document
from app.experiments import (
    Experiment,
    ExperimentIn,
    ResultsResponse,
    create_experiment,
    experiment_results,
    get_assignments,
    list_experiments,
)


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
async def export_document(
    doc_id: str, format: Literal["json", "csv", "jsonl"] = "json"
) -> Response:
    document = await run_in_threadpool(get_document, doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="unknown document")
    room = await websocket_server.get_room(doc_id)
    rows = [Row(**r) for r in room.ydoc.get("rows", type=Array).to_py()]

    if format == "json":
        return Response(
            content=ExportResponse(doc_id=doc_id, rows=rows).model_dump_json(),
            media_type="application/json",
        )

    # training-data formats skip rows that were never filled in
    filled = [(i, r) for i, r in enumerate(rows) if any(r.model_dump().values())]
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["row", *Row.model_fields])
        for i, row in filled:
            writer.writerow([i, *row.model_dump().values()])
        body, media_type = buffer.getvalue(), "text/csv"
    else:
        body = "\n".join(
            json.dumps({"doc_id": doc_id, "row": i, **row.model_dump()}) for i, row in filled
        )
        media_type = "application/jsonl"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{doc_id}.{format}"'},
    )


@app.post("/api/audio/{doc_id}")
async def upload_audio(doc_id: str, file: UploadFile) -> dict:
    data = await file.read()
    await run_in_threadpool(register_document, doc_id)
    record = await run_in_threadpool(
        save_audio, doc_id, file.filename or "audio",
        file.content_type or "application/octet-stream", data,
    )
    return {"doc_id": doc_id, "filename": record.filename, "size": record.size}


@app.api_route("/api/audio/{doc_id}", methods=["GET", "HEAD"])
async def serve_audio(doc_id: str) -> FileResponse:
    record = await run_in_threadpool(get_audio, doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no audio for this document")
    return FileResponse(
        audio_path(doc_id), media_type=record.content_type, filename=record.filename
    )


@app.post("/api/activity")
async def post_activity(batch: ActivityBatch) -> dict:
    stored = await run_in_threadpool(record_events, batch)
    return {"stored": stored}


@app.get("/api/stats/{doc_id}")
async def stats(doc_id: str) -> StatsResponse:
    return await run_in_threadpool(compute_stats, doc_id)


@app.post("/api/experiments")
def post_experiment(spec: ExperimentIn) -> Experiment:
    return create_experiment(spec)


@app.get("/api/experiments")
def experiments() -> list[Experiment]:
    return list_experiments()


@app.get("/api/assignments/{user}")
def assignments(user: str) -> dict[str, str]:
    return get_assignments(user)


@app.get("/api/experiments/{name}/results")
def results(name: str) -> ResultsResponse:
    result = experiment_results(name)
    if result is None:
        raise HTTPException(status_code=404, detail="unknown experiment")
    return result


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
