from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="fastapi-pycrdt-backend")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)
