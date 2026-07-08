import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlmodel import Field, Session, SQLModel, select

from app.db import engine
from app.activity import ACTIVE_GAP_S, TICK_CREDIT_S, ActivityEvent, _gap_sum


class Experiment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    variants: str  # comma-separated
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Assignment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    experiment: str = Field(index=True)
    user: str = Field(index=True)
    variant: str
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExperimentIn(BaseModel):
    name: str
    variants: list[str]


class VariantStats(BaseModel):
    variant: str
    users: int
    active_seconds: float
    edits: int
    edits_per_active_minute: float


class ResultsResponse(BaseModel):
    experiment: str
    variants: list[VariantStats]


def _pick_variant(experiment: str, user: str, variants: list[str]) -> str:
    digest = hashlib.sha256(f"{experiment}:{user}".encode()).digest()
    return variants[int.from_bytes(digest[:4]) % len(variants)]


def create_experiment(spec: ExperimentIn) -> Experiment:
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
    with Session(engine) as session:
        return list(session.exec(select(Experiment)).all())


def get_assignments(user: str) -> dict[str, str]:
    """Sticky per-user variant for every experiment (assigned on first ask)."""
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
