# Multi-phase plan

From empty repo → validated collaboration spike → hackathon transcription
platform with activity telemetry and A/B testing. Each phase has exit
criteria; don't start the next phase until they pass. Phases 0–5 are this
repo; phase 6 is the hackathon build proper.

**Testing approach throughout:** Playwright for Python (headless Chromium)
drives the real UI. Multi-user scenarios = multiple isolated browser contexts
in one test, so CRDT convergence is verified end-to-end, not just unit-level.
`pytest` is the gate for every phase.

## Phase 0 — Skeleton & tooling ✅

Deps (need sign-off before installing; add to `requirements.txt`):
`fastapi`, `uvicorn[standard]`, `pycrdt`, `pycrdt-websocket`, `sqlmodel`,
`pydantic-settings`, and dev deps `pytest`, `pytest-asyncio`, `httpx`,
`playwright`, `pytest-playwright` (+ one-time `playwright install chromium`).

- [x] repo layout: `app/` (FastAPI package), `app/static/` (frontend),
      `tests/`
- [x] `BaseSettings` config (host/port, db path, ystore path)
- [x] FastAPI app serving `StaticFiles` + `/api/health`
- [x] pytest runs: one httpx API test, one Playwright test that loads the
      static page and screenshots it

**Exit:** `pytest -q` green; screenshot of the served page looks right.

## Phase 1 — Prove the CRDT pipe (the risky bit, do it early) ✅

- [x] mount pycrdt-websocket in FastAPI (`ASGIServer` mount first; FastAPI
      websocket-route adapter as fallback) at `ws://…/room/{doc_id}`
- [x] minimal static page: `yjs` + `y-websocket` as pinned CDN ES modules,
      one shared `Y.Map`, a text input bound to it
- [x] Playwright test: two browser contexts, type in A, assert it appears in
      B (and vice versa, and after concurrent edits)

**Exit:** cross-client convergence test green. If interop fails here, the
architecture decision gets revisited *before* any UI work.

## Phase 2 — Collaborative spreadsheet + awareness ✅

- [x] grid UI over `Y.Array` of row `Y.Map`s (transcription-shaped columns:
      start, end, speaker, text, noise condition)
- [x] cell editing, row add/delete
- [x] awareness: per-user color + name; other users' selected cells shown as
      colored outlines with name tags
- [x] Playwright tests: concurrent edits to different cells converge; edit to
      same cell converges (last-writer is fine); context B sees context A's
      selection highlight (assert on DOM, plus screenshot for eyeballing)

**Exit:** two headless "users" collaborate on the grid in tests; screenshots
show both cursors.

## Phase 3 — Persistence & export ✅

- [x] YStore (built-in SQLite store) wired into the room manager
- [x] SQLModel owns app tables (documents/rooms registry); YStore owns the
      CRDT update log — separate files/concerns
- [x] `GET /api/documents` (documents auto-register on first ws connection
      instead of an explicit `POST /api/documents`)
- [x] `GET /api/export/{doc_id}` — server-side pycrdt read → pydantic rows →
      JSON (CSV variant optional)
- [x] restart test: edit → stop server → start → state intact (Playwright)

**Exit:** kill-and-restart test green; export returns the grid as clean rows.

## Phase 4 — Activity telemetry ✅

Goal: know how long tasks *actively* take, per user per document.

- [x] client `activity.js`: batches events —
      `visibilitychange` (tab hidden/shown), window `focus`/`blur`,
      input activity ticks (throttled keystroke/mouse), heartbeat while
      visible, `pagehide` flush via `navigator.sendBeacon`
- [x] `POST /api/activity` ingesting event batches → SQLModel `activity_event`
      table (user, doc, event type, client timestamp, server timestamp)
- [x] active-time derivation: sessionize events server-side; gap > N seconds
      without input = idle; hidden/blurred = inactive. Expose
      `GET /api/stats/{doc_id}` (per-user active seconds, wall-clock, edits)
- [x] Playwright test: simulate focus, typing, tab-hide, return → assert
      derived active time excludes the hidden window

**Exit:** stats endpoint reports plausible active vs. wall-clock time for a
scripted session.

## Phase 5 — A/B experiment harness ✅

Goal: measure whether an AI feature actually improves productivity.

- [x] SQLModel tables: `experiment`, `assignment` (user × experiment →
      variant, sticky, assigned server-side), optional `exposure` log
- [x] client fetches its variants at load; features gated by variant flag
- [x] outcome metrics derived from existing data: active seconds per row
      completed, rows/hour, edit counts — grouped by variant via
      `GET /api/experiments/{id}/results`
- [x] a dummy experiment end-to-end (e.g. variant B shows a fake "AI
      suggestion" button) proving assignment → exposure → metrics pipeline

**Exit:** results endpoint shows per-variant productivity numbers from a
scripted two-user session.

## Phase 6 — Hackathon build (the real tool) ✅ (core)

- [x] audio: per-document upload + `<audio>` player, row ⇄ playback linking
      (row-number click / Alt+G seek; Alt+S / Alt+E stamp current time into
      start/end cells; Alt+P play/pause)
- [x] keyboard-first annotation flow (Enter advances a row and grows the grid
      on the last row; tab navigation is native)
- [x] lightweight identity (annotator name persisted in localStorage, color
      derived from name; no real auth)
- [x] lobby page at `/` — list, open, create documents
- [x] export pipeline: `?format=csv|jsonl` training-data formats (empty rows
      skipped)
- [x] deployment story: single uvicorn box, documented in README
- [ ] real AI features to A/B (ASR pre-fill, autocomplete, speaker
      suggestion) — the harness + a fake suggest feature exist behind the
      `ai-suggest` flag; swap in a real model during hackathon week
- [ ] speaker quick-picks / per-cell validation — polish, as needed

## Standing rules

- Python only; interpreter is
  `C:\Users\avery\anaconda3\envs\fastapi-pycrdt-backend\python.exe`. No
  Node/npm ever — frontend deps only as pinned CDN ES-module URLs.
- every phase ends with `pytest -q` green and, where UI is involved, a
  Playwright screenshot check
- dependency changes go through `requirements.txt` with sign-off
