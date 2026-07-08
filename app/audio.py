"""Per-document audio upload storage: one audio file per room.

The file bytes live on disk (`<data_dir>/audio/<doc_id>`, named by room id
rather than by original filename); `AudioFile` only stores metadata needed
to serve it back with correct headers and to detect whether a document has
audio at all.
"""

from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, select

from app.config import settings
from app.db import engine


class AudioFile(SQLModel, table=True):
    """Metadata for the audio file attached to one document.

    Attributes:
        doc_id: The document/room this audio belongs to (one file per doc;
            re-uploading replaces both the row and the file on disk).
        filename: Original filename, restored in the `Content-Disposition`
            header when serving.
        content_type: MIME type as reported by the uploading client.
        size: File size in bytes.
    """

    id: int | None = Field(default=None, primary_key=True)
    doc_id: str = Field(unique=True, index=True)
    filename: str
    content_type: str
    size: int
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def audio_path(doc_id: str) -> Path:
    """Return the on-disk path for `doc_id`'s audio file, creating the
    containing `audio/` directory if needed.

    Note this does not guarantee the file itself exists — check the
    `AudioFile` table (via `get_audio`) for that.
    """
    audio_dir = settings.data_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir / doc_id


def save_audio(doc_id: str, filename: str, content_type: str, data: bytes) -> AudioFile:
    """Write an uploaded audio file to disk and upsert its metadata row.

    Args:
        doc_id: The document/room to attach the audio to.
        filename: Original filename from the upload.
        content_type: MIME type from the upload.
        data: Raw file bytes.

    Returns:
        The stored (inserted or updated) `AudioFile` record.
    """
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
    """Look up the audio metadata for `doc_id`, or `None` if none uploaded."""
    with Session(engine) as session:
        return session.exec(select(AudioFile).where(AudioFile.doc_id == doc_id)).first()
