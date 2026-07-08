from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, select

from app.config import settings
from app.db import engine


class AudioFile(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    doc_id: str = Field(unique=True, index=True)
    filename: str
    content_type: str
    size: int
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def audio_path(doc_id: str) -> Path:
    audio_dir = settings.data_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir / doc_id


def save_audio(doc_id: str, filename: str, content_type: str, data: bytes) -> AudioFile:
    audio_path(doc_id).write_bytes(data)
    with Session(engine) as session:
        record = session.exec(select(AudioFile).where(AudioFile.doc_id == doc_id)).first()
        if record is None:
            record = AudioFile(doc_id=doc_id, filename=filename,
                               content_type=content_type, size=len(data))
        else:
            record.filename = filename
            record.content_type = content_type
            record.size = len(data)
            record.uploaded_at = datetime.now(timezone.utc)
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def get_audio(doc_id: str) -> AudioFile | None:
    with Session(engine) as session:
        return session.exec(select(AudioFile).where(AudioFile.doc_id == doc_id)).first()
