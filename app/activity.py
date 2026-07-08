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
    id: int | None = Field(default=None, primary_key=True)
    doc_id: str = Field(index=True)
    user: str = Field(index=True)
    type: str
    client_ts: float  # epoch seconds, client clock
    server_ts: float  # epoch seconds, server clock


class EventIn(BaseModel):
    type: str
    ts: float  # epoch milliseconds, client clock


class ActivityBatch(BaseModel):
    doc_id: str
    user: str
    events: list[EventIn]


class UserStats(BaseModel):
    user: str
    events: int
    active_seconds: float
    open_seconds: float
    first_seen: float
    last_seen: float


class StatsResponse(BaseModel):
    doc_id: str
    users: list[UserStats]


def record_events(batch: ActivityBatch) -> int:
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
    if not timestamps:
        return 0.0
    total = credit  # the last event extends activity by one credit
    for earlier, later in zip(timestamps, timestamps[1:]):
        gap = later - earlier
        total += gap if gap <= max_gap else credit
    return total


def compute_stats(doc_id: str) -> StatsResponse:
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
