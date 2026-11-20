"""Punctul de intrare al API-ului ContaHub."""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db

app = FastAPI(title="ContaHub API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["sistem"])
def health(db: Session = Depends(get_db)) -> dict:
    """Starea serviciului și a conexiunii la baza de date."""
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001 — /health nu are voie să cadă
        database = "indisponibilă"
    return {"status": "ok" if database == "ok" else "degradat", "database": database}
