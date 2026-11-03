"""FastAPI application entry point. Run with: uvicorn khataiq.api.main:app --reload"""

from fastapi import FastAPI

app = FastAPI(title="KhataIQ", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe: the process is up. It deliberately does not touch the database."""
    return {"status": "ok"}
