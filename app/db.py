from datetime import datetime, timezone

from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.config import settings

engine = create_engine(f"sqlite:///{settings.db_path}")


class Document(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    doc_id: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def register_document(doc_id: str) -> None:
    with Session(engine) as session:
        existing = session.exec(select(Document).where(Document.doc_id == doc_id)).first()
        if existing is None:
            session.add(Document(doc_id=doc_id))
            session.commit()


def get_document(doc_id: str) -> Document | None:
    with Session(engine) as session:
        return session.exec(select(Document).where(Document.doc_id == doc_id)).first()


def list_documents() -> list[Document]:
    with Session(engine) as session:
        return list(session.exec(select(Document).order_by(Document.created_at)).all())
