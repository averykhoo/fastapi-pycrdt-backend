"""Application-level SQLModel database: the document registry.

This is deliberately separate from the CRDT update log (see `app.collab`'s
`AppYStore`, backed by `settings.ystore_path`) — the registry only tracks
*which* documents (rooms) exist and when they were first seen; the actual
grid content lives in the Yjs document itself.
"""

from datetime import datetime, timezone

from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.config import settings

engine = create_engine(f"sqlite:///{settings.db_path}")


class Document(SQLModel, table=True):
    """A registered document (collaboration room).

    Attributes:
        doc_id: The room name, as used in the websocket path and URLs.
        created_at: When this document was first seen by the server.
    """

    id: int | None = Field(default=None, primary_key=True)
    doc_id: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    """Create all SQLModel tables that don't already exist.

    Called once from the FastAPI app's lifespan on startup. Safe to call
    repeatedly — `create_all` is a no-op for existing tables.
    """
    SQLModel.metadata.create_all(engine)


def register_document(doc_id: str) -> None:
    """Ensure `doc_id` has a `Document` row, inserting one if this is the
    first time it's been seen.

    Args:
        doc_id: The room name to register.
    """
    with Session(engine) as session:
        existing = session.exec(select(Document).where(Document.doc_id == doc_id)).first()
        if existing is None:
            session.add(Document(doc_id=doc_id))
            session.commit()


def get_document(doc_id: str) -> Document | None:
    """Look up a registered document by id, or `None` if it doesn't exist."""
    with Session(engine) as session:
        return session.exec(select(Document).where(Document.doc_id == doc_id)).first()


def list_documents() -> list[Document]:
    """Return every registered document, oldest first (for the lobby page)."""
    with Session(engine) as session:
        return list(session.exec(select(Document).order_by(Document.created_at)).all())
