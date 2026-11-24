"""Sincronizarea automată a surselor de documente: interval și starea ultimei rulări.

Revision ID: fixb_0001
Revises: fix9_0001
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op

revision = "fixb_0001"
down_revision = "fix9_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_sources", sa.Column("sync_interval_minutes", sa.Integer(), server_default=sa.text("60"), nullable=False))
    for name, typ in (
        ("last_sync_at", sa.DateTime(timezone=True)),
        ("last_status", sa.String()),
        ("last_error", sa.Text()),
        ("last_found", sa.Integer()),
        ("last_added", sa.Integer()),
        ("last_duplicates", sa.Integer()),
        ("last_failed", sa.Integer()),
    ):
        op.add_column("document_sources", sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    for name in ("last_failed", "last_duplicates", "last_added", "last_found", "last_error", "last_status", "last_sync_at", "sync_interval_minutes"):
        op.drop_column("document_sources", name)
