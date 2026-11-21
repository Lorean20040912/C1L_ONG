"""Asistentul AI: conversații și mesaje.

Revision ID: ai_0001
Revises: mrg_0003
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ai_0001"
down_revision = "mrg_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String()),
        sa.Column("context", postgresql.JSONB()),
        sa.Column("created_at", postgresql.TIMESTAMP(), server_default=sa.text("now()")),
    )
    op.create_index("ix_ai_conversations_org_user", "ai_conversations", ["organization_id", "user_id"])
    op.create_table(
        "ai_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", postgresql.UUID(), sa.ForeignKey("ai_conversations.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("tool_calls", postgresql.JSONB()),
        sa.Column("sources", postgresql.JSONB()),
        sa.Column("created_at", postgresql.TIMESTAMP(), server_default=sa.text("now()")),
    )
    op.create_index("ix_ai_messages_conversation_id", "ai_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("ai_messages")
    op.drop_table("ai_conversations")
