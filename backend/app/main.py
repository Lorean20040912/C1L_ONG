"""Punctul de intrare al API-ului ContaHub."""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.router import router as auth_router
from app.catalogs.router import router as catalogs_router
from app.core.config import get_settings
from app.core.db import get_db
from app.documents.invoices_router import router as invoices_router
from app.documents.payments_router import router as payments_router
from app.documents.router import router as documents_router
from app.grants.router import router as grants_router
from app.posting.router import router as posting_router
from app.posting.rules_router import router as rules_router
from app.workspaces.router import router as workspaces_router

app = FastAPI(title="ContaHub API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(catalogs_router)
app.include_router(workspaces_router)
app.include_router(documents_router)
app.include_router(invoices_router)
app.include_router(payments_router)
app.include_router(posting_router)
app.include_router(rules_router)
app.include_router(grants_router)


@app.get("/health", tags=["sistem"])
def health(db: Session = Depends(get_db)) -> dict:
    """Starea serviciului și a conexiunii la baza de date."""
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001 — /health nu are voie să cadă
        database = "indisponibilă"
    return {"status": "ok" if database == "ok" else "degradat", "database": database}
