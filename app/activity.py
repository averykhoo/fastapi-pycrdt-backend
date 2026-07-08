"""Active-time telemetry: ingestion of client activity events and derivation
of per-user active-vs-open time from them.

The client (`app/static/activity.js`) reports a stream of typed events —
`input` ticks while the user interacts, `heartbeat` every 2s while the tab is
visible, plus `focus`/`blur`/`hidden`/`visible`/`unload`. This module doesn't
interpret event *types* beyond `input` (used for active time) and the full
timestamp series (used for open/wall-clock time) — see `_gap_sum`.
"""

from time import time

from pydantic import BaseModel
from sqlmodel import Field, Session, SQLModel, select

from app.db import engine

# An "input" tick arrives at most every 0.5s while the user interacts, so
# consecutive-tick gaps within ACTIVE_GAP_S count as active time; an isolated
# tick earns TICK_CREDIT_S. Heartbeats arrive every 2s while the page is
# visible, so any gap above OPEN_GAP_S means the tab was hidden or closed.
TICK_CREDIT_S = 0.5
ACTIVE_GAP_S = 3.0
OPEN_GAP_S = 3.0


class ActivityEvent(SQLModel, table=True):
    """One client-reported activity event, persisted as-received.

    Attributes:
        doc_id: The document/room the event was reported from.
        user: The annotator name that reported it.
        type: Event kind, e.g. `"input"`, `"heartbeat"`, `"edit"`, `"hidden"`,
            `"visible"`, `"focus"`, `"blur"`, `"unload"`.
        client_ts: Epoch seconds on the *client's* clock — used for all
            active/open-time math so gaps reflect wall-clock reality even if
            the batch arrived late.
        server_ts: Epoch seconds when the server recorded the event —
            informational only, not used in stats derivation.
    """

    id: int | None = Field(default=None, primary_key=True)
    doc_id: str = Field(index=True)
    user: str = Field(index=True)
    type: str
    client_ts: float
    server_ts: float


class EventIn(BaseModel):
    """A single event as sent by the client, before server-side timestamping.

    Attributes:
        type: Event kind (see `ActivityEvent.type`).
        ts: Epoch *milliseconds* on the client's clock (JS `Date.now()`).
    """

    type: str
    ts: float


class ActivityBatch(BaseModel):
    """The request body for `POST /api/activity`: one user's queued events."""

    doc_id: str
    user: str
    events: list[EventIn]


class UserStats(BaseModel):
    """Derived active/open time for one user within one document.

    Attributes:
        events: Total events recorded for this user.
        active_seconds: Estimated time spent actively interacting (typing,
            clicking, scrolling) — see `_gap_sum` for the derivation.
        open_seconds: Estimated time the document was open and visible in a
            tab, regardless of whether the user was actively interacting.
        first_seen: Client-clock epoch seconds of the first recorded event.
        last_seen: Client-clock epoch seconds of the last recorded event.
    """

    user: str
    events: int
    active_seconds: float
    open_seconds: float
    first_seen: float
    last_seen: float


class StatsResponse(BaseModel):
    """Response body for `GET /api/stats/{doc_id}`."""

    doc_id: str
    users: list[UserStats]


def record_events(batch: ActivityBatch) -> int:
    """Persist a batch of client-reported events, stamped with server time.

    Args:
        batch: The events reported by one client since its last flush.

    Returns:
        The number of events stored.
    """
    now = time()
    with Session(engine) as session:
        for event in batch.events:
            session.add(ActivityEvent(
                doc_id=batch.doc_id,
                user=batch.user,
                type=event.type,
                client_ts=event.ts / 1000.0,
                server_ts=now,
            ))
        session.commit()
    return len(batch.events)


def _gap_sum(timestamps: list[float], max_gap: float, credit: float) -> float:
    """Sum elapsed time across a sorted timestamp series, treating each gap
    as either "continuously active" or an isolated blip.

    This is the core active/open-time heuristic: consecutive timestamps
    closer together than `max_gap` are assumed to represent one unbroken
    span of activity, so the gap between them counts in full. A gap *larger*
    than `max_gap` means activity stopped and later resumed, so only
    `credit` (a fixed, small allowance) is attributed to the isolated event
    rather than the whole gap — otherwise a single stray click after a
    long idle period would appear to be hours of "active" time.

    Args:
        timestamps: Sorted epoch-second timestamps (e.g. all `input` ticks,
            or all events, for one user).
        max_gap: Largest gap (seconds) between consecutive timestamps that
            still counts as one continuous span.
        credit: Seconds attributed to an isolated event (both the very last
            timestamp, and any timestamp following a gap larger than
            `max_gap`).

    Returns:
        Estimated total seconds of activity represented by `timestamps`.
    """
    if not timestamps:
        return 0.0
    total = credit  # the last event extends activity by one credit
    for earlier, later in zip(timestamps, timestamps[1:]):
        gap = later - earlier
        total += gap if gap <= max_gap else credit
    return total


def compute_stats(doc_id: str) -> StatsResponse:
    """Derive per-user active/open time for a document from its stored
    activity events.

    Args:
        doc_id: The document/room to compute stats for.

    Returns:
        A `StatsResponse` with one `UserStats` per user who has reported any
        activity for `doc_id`, sorted by username. Empty if no events exist.
    """
    with Session(engine) as session:
        events = session.exec(
            select(ActivityEvent)
            .where(ActivityEvent.doc_id == doc_id)
            .order_by(ActivityEvent.client_ts)
        ).all()

    users: dict[str, list[ActivityEvent]] = {}
    for event in events:
        users.setdefault(event.user, []).append(event)

    stats = []
    for user, user_events in sorted(users.items()):
        all_ts = [e.client_ts for e in user_events]
        input_ts = [e.client_ts for e in user_events if e.type == "input"]
        stats.append(UserStats(
            user=user,
            events=len(user_events),
            active_seconds=round(_gap_sum(input_ts, ACTIVE_GAP_S, TICK_CREDIT_S), 3),
            open_seconds=round(_gap_sum(all_ts, OPEN_GAP_S, 0.0), 3),
            first_seen=all_ts[0],
            last_seen=all_ts[-1],
        ))
    return StatsResponse(doc_id=doc_id, users=stats)
