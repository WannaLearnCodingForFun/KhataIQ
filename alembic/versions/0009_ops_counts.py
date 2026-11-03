"""ops_counts(): two numbers for monitoring, across all orgs.

Queue depth and dead-letter count are operational facts about the whole system, but the app
role sees only one tenant at a time. This SECURITY DEFINER function returns just the two
counts and nothing else, so /metrics doesn't need a role that can read every tenant's rows.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION ops_counts(OUT unpublished_outbox bigint, OUT dead_runs bigint)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT (SELECT count(*) FROM outbox WHERE published_at IS NULL),
                   (SELECT count(*) FROM pipeline_runs r WHERE r.status = 'dead'
                      AND NOT EXISTS (SELECT 1 FROM pipeline_runs later
                                      WHERE later.upload_id = r.upload_id
                                        AND later.stage = r.stage
                                        AND later.attempt_no > r.attempt_no))
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION ops_counts() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION ops_counts() TO khataiq_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION ops_counts()")
