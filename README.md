# fastapi-pycrdt-backend — Yjs collaboration spike

Feasibility spike for a hackathon project: a **"multiplayer" manual audio
transcription platform** for human annotation. Annotators currently transcribe
into shared Excel sheets; nothing free/open does real-time collaborative
transcription well, and we need to collect data. The plan is Yjs on the
frontend with a **pure-Python backend** (no npm/Node server) — FastAPI +
[pycrdt](https://github.com/y-crdt/pycrdt) /
[pycrdt-websocket](https://github.com/y-crdt/pycrdt-websocket).

This repo exists to prove that architecture works before the hackathon, using
a small Excel-like test app.

## Why a spreadsheet as the test app

The eventual transcription UI is essentially a grid: one row per utterance,
with columns like

| column | example |
|---|---|
| start timestamp | `00:01:23.400` |
| end timestamp | `00:01:26.900` |
| speaker | `SPK_02 / "Alice"` |
| transcript text | `so what I was saying was…` |
| noise condition | `clean / babble / music` |
| (later) flags, notes, confidence | … |

Annotators already work this way in Excel, so a collaboratively editable
spreadsheet exercises exactly the data shapes and interactions the real tool
needs — concurrent cell edits, row insertion/reordering, and seeing where
teammates are working.

## What this spike must prove

1. **Backend feasibility (the big one):** pycrdt-websocket's server can be
   mounted inside a FastAPI app (via its ASGI server / a FastAPI websocket
   route adapter) and correctly syncs Yjs docs with browser clients speaking
   the standard `y-websocket` protocol.
2. **No-npm frontend:** Yjs + `y-websocket` provider loaded as ES modules
   straight from a CDN (e.g. esm.sh / jsdelivr) into plain static HTML served
   by FastAPI `StaticFiles`. No bundler, no `package.json`.
3. **Awareness:** shared presence works through the Python relay — each
   client gets a color + name, and everyone sees others' cursor position and
   currently selected cell(s) as colored highlights.
4. **Persistence:** document updates survive a server restart, stored via a
   YStore backed by SQLite/SQLModel.
5. **Data extraction:** the server can read the Y doc *server-side* (pycrdt)
   and export the grid as structured rows (pydantic models → JSON API). This
   is critical — the whole point is collecting clean data, not just editing it.
6. **Config & app plumbing:** `pydantic-settings` `BaseSettings` for config,
   normal JSON REST endpoints coexisting with the CRDT websocket (e.g. list
   rooms/documents, export endpoint).
7. **Activity telemetry:** a DB (SQLModel) tracks per-user *active* time —
   focus/blur, tab visibility, input heartbeats, navigation away — so we can
   measure how long annotation tasks actually take. This is the substrate for
   **A/B testing AI features** against real productivity (active seconds per
   row completed), not vibes.

See [PLAN.md](PLAN.md) for the phased plan from empty repo to hackathon tool.

## Test app spec

A small collaborative spreadsheet:

- fixed small grid to start (e.g. 20 rows × 6 columns), later: add/remove rows
- cell editing synced live between ≥2 browsers
- shared cursors: each user's selected cell outlined/highlighted in their color,
  with a name tag
- document data model (to mirror the transcription tool):
  - `Y.Array` of rows, each row a `Y.Map` of `column → value`
  - text cells could later become `Y.Text` for character-level merging; plain
    values are fine for the spike
- one room per document; room name in the websocket path

## Architecture sketch

```
browser (static HTML + yjs/y-websocket from CDN)
   │  ws://…/room/{doc_id}          │  http://…/api/…
   ▼                                ▼
FastAPI app ──── mounts ──── pycrdt-websocket WebsocketServer/ASGIServer
   │                                │
   ├── pydantic JSON APIs (export, room list)
   └── SQLModel/SQLite  ◄── YStore (update log / snapshots)
```

## Success criteria

- [x] Two browsers edit the same grid; edits converge with no lost updates
- [x] Selections/cursors visible cross-client in distinct colors
- [x] Kill and restart the server → document state comes back
- [x] `GET /api/export/{doc_id}` returns the grid as JSON rows
- [x] Zero Node/npm anywhere in the repo

## Open questions / risks to answer while building

- Does pycrdt-websocket's protocol implementation fully interop with the
  current `y-websocket` client (sync **and** awareness messages)? Version
  pinning may matter.
- FastAPI integration style: mount the provided `ASGIServer` vs. adapt
  FastAPI's `WebSocket` object into the interface `WebsocketServer.serve()`
  expects. Try mount first; keep the adapter as fallback.
- YStore: use the built-in SQLite store as-is, or wrap SQLModel? Built-in
  first — SQLModel can own app-level tables (rooms, users, export snapshots)
  instead of the update log.
- Update-log growth: does the store squash/compact, and do we care at
  hackathon scale? (Probably not — note it and move on.)
- CDN ESM pitfalls: `yjs` must resolve to a *single* module instance across
  imports (duplicate-yjs is a classic bug); pin exact versions in import URLs.

## Out of scope for the spike

Audio playback/waveforms, auth, per-cell validation, undo history UI, mobile.
Those are hackathon-week problems; this repo only de-risks the sync backend.
