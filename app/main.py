"""FastAPI application: routes for the collaborative transcription grid.

Wires together the CRDT websocket room (`app.collab`), the document registry
and audio store (`app.db`, `app.audio`), activity telemetry (`app.activity`),
the A/B experiment harness (`app.experiments`), and the static frontend —
all mounted on a single FastAPI app so there's one process to run.
"""

import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Literal

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
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create SQLModel tables and start/stop the CRDT websocket server
    alongside the FastAPI app's own lifecycle."""
    init_db()
    async with websocket_server:
        yield


app = FastAPI(title="fastapi-pycrdt-backend", lifespan=lifespan)


class Row(BaseModel):
    """One row of the transcription grid — mirrors the Yjs `Y.Map` schema
    used client-side (`app/static/index.html`'s `COLUMNS`)."""

    start: str = ""
    end: str = ""
    speaker: str = ""
    text: str = ""
    noise: str = ""


class ExportResponse(BaseModel):
    """Response body for `GET /api/export/{doc_id}?format=json`."""

    doc_id: str
    rows: list[Row]


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe used by the test harness to know the server is up."""
    return {"status": "ok"}


@app.get("/api/documents")
def documents() -> list[Document]:
    """List every registered document, for the lobby page."""
    return list_documents()


@app.get("/api/export/{doc_id}")
async def export_document(
    doc_id: str, format: Literal["json", "csv", "jsonl"] = "json"
) -> Response:
    """Export a document's grid as structured data.

    Reads the live Yjs document server-side (via pycrdt, not a browser) so
    export reflects the current collaborative state exactly. `json` returns
    every row including untouched ones; `csv`/`jsonl` are training-data
    formats that omit rows with no data in any column.

    Args:
        doc_id: The document to export.
        format: Output format — `json` (default, full `ExportResponse`),
            `csv`, or `jsonl` (one JSON object per non-empty row).

    Raises:
        HTTPException: 404 if `doc_id` is not a registered document.
    """
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
async def upload_audio(doc_id: str, file: UploadFile) -> dict[str, str | int]:
    """Upload (or replace) the audio file attached to a document.

    Also registers `doc_id` as a document if it isn't one yet, so uploading
    audio can be the first action taken on a brand-new room.

    Args:
        doc_id: The document/room to attach the audio to.
        file: The uploaded audio file (any content type the browser can play).

    Returns:
        A summary of the stored file: `doc_id`, `filename`, `size`.
    """
    data = await file.read()
    await run_in_threadpool(register_document, doc_id)
    record = await run_in_threadpool(
        save_audio, doc_id, file.filename or "audio",
        file.content_type or "application/octet-stream", data,
    )
    return {"doc_id": doc_id, "filename": record.filename, "size": record.size}


@app.api_route("/api/audio/{doc_id}", methods=["GET", "HEAD"])
async def serve_audio(doc_id: str) -> FileResponse:
    """Serve a document's uploaded audio file for playback.

    Registered for both GET and HEAD — FastAPI does not auto-answer HEAD for
    a GET-only route, and the frontend HEADs this endpoint to detect whether
    audio exists before showing the `<audio>` player.

    Raises:
        HTTPException: 404 if no audio has been uploaded for `doc_id`.
    """
    record = await run_in_threadpool(get_audio, doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no audio for this document")
    return FileResponse(
        audio_path(doc_id), media_type=record.content_type, filename=record.filename
    )


@app.post("/api/activity")
async def post_activity(batch: ActivityBatch) -> dict[str, int]:
    """Ingest a batch of client-reported activity events (see `app.activity`)."""
    stored = await run_in_threadpool(record_events, batch)
    return {"stored": stored}


@app.get("/api/stats/{doc_id}")
async def stats(doc_id: str) -> StatsResponse:
    """Return derived per-user active/open time for a document."""
    return await run_in_threadpool(compute_stats, doc_id)


@app.post("/api/experiments")
def post_experiment(spec: ExperimentIn) -> Experiment:
    """Register a new A/B experiment (idempotent by name)."""
    return create_experiment(spec)


@app.get("/api/experiments")
def experiments() -> list[Experiment]:
    """List every registered A/B experiment."""
    return list_experiments()


@app.get("/api/assignments/{user}")
def assignments(user: str) -> dict[str, str]:
    """Return `user`'s sticky variant assignment for every experiment,
    assigning one on first request if the user has none yet."""
    return get_assignments(user)


@app.get("/api/experiments/{name}/results")
def results(name: str) -> ResultsResponse:
    """Return per-variant productivity metrics for an experiment.

    Raises:
        HTTPException: 404 if no experiment named `name` exists.
    """
    result = experiment_results(name)
    if result is None:
        raise HTTPException(status_code=404, detail="unknown experiment")
    return result


@app.websocket("/room/{doc_id}")
async def collab_room(websocket: WebSocket, doc_id: str) -> None:
    """Accept a websocket connection and hand it to the CRDT room for
    `doc_id`, registering the document on first connection.

    This is the sync/awareness endpoint the browser's `y-websocket`
    `WebsocketProvider` connects to; all Yjs protocol handling happens
    inside `websocket_server.serve()` (see `app.collab`).
    """
    await run_in_threadpool(register_document, doc_id)
    await websocket.accept()
    await websocket_server.serve(FastAPIWebsocket(websocket, doc_id))


# Serves app/static/ at the root — must be mounted last so it doesn't shadow
# the /api/* and /room/* routes declared above.
app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)
