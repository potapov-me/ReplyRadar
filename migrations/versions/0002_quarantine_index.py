"""index on processing_quarantine for backfill NOT EXISTS queries

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-12

Покрывает коррелированные NOT EXISTS (message_id, stage, reviewed_at IS NULL)
в engine._backfill_loop и /status endpoint.
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_processing_quarantine_active
        ON processing_quarantine (message_id, stage)
        WHERE reviewed_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_processing_quarantine_active")
