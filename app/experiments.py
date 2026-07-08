"""A/B experiment harness: variant assignment and productivity results.

Assignment is deterministic (hashed from experiment name + username) so it
never needs a lookup to decide a brand-new user's variant, and is made
"sticky" by persisting the first result to the `Assignment` table — later
calls for the same (experiment, user) pair reuse that row instead of
re-hashing, so a variant never changes under a returning user even if the
experiment's variant list is edited later.

Results join assignments against `app.activity`'s event log (not a separate
exposure log) so productivity metrics — active seconds, edits, edits per
active minute — reuse the same telemetry pipeline built for `app.activity`.
"""

import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlmodel import Field, Session, SQLModel, select

from app.activity import ACTIVE_GAP_S, TICK_CREDIT_S, ActivityEvent, _gap_sum
from app.db import engine


class Experiment(SQLModel, table=True):
    """A named A/B experiment and its candidate variants.

    Attributes:
        name: Unique experiment identifier (e.g. `"ai-suggest"`), also used
            as the key clients look up in `GET /api/assignments/{user}`.
        variants: Comma-separated variant names (e.g. `"control,ai"`).
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    variants: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Assignment(SQLModel, table=True):
    """The variant a specific user was assigned for a specific experiment,
    persisted on first assignment so it stays sticky across sessions."""

    id: int | None = Field(default=None, primary_key=True)
    experiment: str = Field(index=True)
    user: str = Field(index=True)
    variant: str
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExperimentIn(BaseModel):
    """Request body for `POST /api/experiments`."""

    name: str
    variants: list[str]


class VariantStats(BaseModel):
    """Aggregated productivity metrics for one variant of one experiment.

    Attributes:
        users: Number of assigned users who have reported any activity.
        active_seconds: Summed `active_seconds` (see `app.activity`) across
            all of the variant's users.
        edits: Count of `"edit"`-type activity events across all users.
        edits_per_active_minute: `edits` normalized by `active_seconds`; the
            headline "did this variant make people more productive?" number.
    """

    variant: str
    users: int
    active_seconds: float
    edits: int
    edits_per_active_minute: float


class ResultsResponse(BaseModel):
    """Response body for `GET /api/experiments/{name}/results`."""

    experiment: str
    variants: list[VariantStats]


def _pick_variant(experiment: str, user: str, variants: list[str]) -> str:
    """Deterministically map (experiment, user) to one of `variants`.

    Hash-based so assignment requires no shared random state and is stable
    for a given input — used as the fallback when a user has no persisted
    `Assignment` row yet.
    """
    digest = hashlib.sha256(f"{experiment}:{user}".encode()).digest()
    return variants[int.from_bytes(digest[:4]) % len(variants)]


def create_experiment(spec: ExperimentIn) -> Experiment:
    """Create an experiment, or return the existing one if `spec.name` is
    already registered (idempotent — re-posting the same experiment is a
    no-op rather than an error).
    """
    with Session(engine) as session:
        existing = session.exec(select(Experiment).where(Experiment.name == spec.name)).first()
        if existing is not None:
            return existing
        experiment = Experiment(name=spec.name, variants=",".join(spec.variants))
        session.add(experiment)
        session.commit()
        session.refresh(experiment)
        return experiment


def list_experiments() -> list[Experiment]:
    """Return every registered experiment."""
    with Session(engine) as session:
        return list(session.exec(select(Experiment)).all())


def get_assignments(user: str) -> dict[str, str]:
    """Sticky per-user variant for every experiment (assigned on first ask).

    Args:
        user: The annotator name to resolve/assign variants for.

    Returns:
        A mapping of experiment name to assigned variant, covering every
        registered experiment.
    """
    assignments: dict[str, str] = {}
    with Session(engine) as session:
        for experiment in session.exec(select(Experiment)).all():
            existing = session.exec(
                select(Assignment)
                .where(Assignment.experiment == experiment.name, Assignment.user == user)
            ).first()
            if existing is None:
                variant = _pick_variant(experiment.name, user, experiment.variants.split(","))
                session.add(Assignment(experiment=experiment.name, user=user, variant=variant))
                session.commit()
                assignments[experiment.name] = variant
            else:
                assignments[experiment.name] = existing.variant
    return assignments


def experiment_results(name: str) -> ResultsResponse | None:
    """Compute per-variant productivity metrics for an experiment.

    Args:
        name: The experiment to summarize.

    Returns:
        A `ResultsResponse` with one `VariantStats` per configured variant
        (present even if a variant has zero users so far), or `None` if no
        experiment named `name` exists.
    """
    with Session(engine) as session:
        experiment = session.exec(select(Experiment).where(Experiment.name == name)).first()
        if experiment is None:
            return None
        assignments = session.exec(select(Assignment).where(Assignment.experiment == name)).all()

        per_variant: dict[str, dict] = {
            v: {"users": 0, "active": 0.0, "edits": 0} for v in experiment.variants.split(",")
        }
        for assignment in assignments:
            events = session.exec(
                select(ActivityEvent)
                .where(ActivityEvent.user == assignment.user)
                .order_by(ActivityEvent.client_ts)
            ).all()
            if not events:
                continue
            bucket = per_variant.setdefault(
                assignment.variant, {"users": 0, "active": 0.0, "edits": 0})
            input_ts = [e.client_ts for e in events if e.type == "input"]
            bucket["users"] += 1
            bucket["active"] += _gap_sum(input_ts, ACTIVE_GAP_S, TICK_CREDIT_S)
            bucket["edits"] += sum(1 for e in events if e.type == "edit")

    return ResultsResponse(
        experiment=name,
        variants=[
            VariantStats(
                variant=variant,
                users=data["users"],
                active_seconds=round(data["active"], 3),
                edits=data["edits"],
                edits_per_active_minute=round(
                    data["edits"] / (data["active"] / 60.0), 3) if data["active"] else 0.0,
            )
            for variant, data in per_variant.items()
        ],
    )
