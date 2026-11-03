"""Outbox relay functions.

The relay publishes jobs for every org, so it can't run inside one tenant's RLS scope. Rather
than giving the worker a role that bypasses RLS on everything, it gets two narrow SECURITY
DEFINER functions:

  outbox_claim(n)            the oldest n unpublished rows, locked FOR UPDATE SKIP LOCKED.
                             The row locks belong to the caller's transaction, so a second
                             relay running at the same time skips them instead of waiting or
                             double-publishing.
  outbox_mark_published(ids) stamps published_at; called in the same transaction, after the
                             jobs were handed to the broker.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION outbox_claim(p_limit integer)
        RETURNS TABLE (id bigint, org_id bigint, topic varchar, payload jsonb)
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT o.id, o.org_id, o.topic, o.payload
            FROM outbox o
            WHERE o.published_at IS NULL
            ORDER BY o.id
            LIMIT p_limit
            FOR UPDATE SKIP LOCKED
        $$
    """)
    op.execute("""
        CREATE FUNCTION outbox_mark_published(p_ids bigint[])
        RETURNS integer
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            WITH done AS (
                UPDATE outbox SET published_at = now()
                WHERE id = ANY(p_ids) AND published_at IS NULL
                RETURNING 1
            )
            SELECT count(*)::integer FROM done
        $$
    """)
    for fn in ("outbox_claim(integer)", "outbox_mark_published(bigint[])"):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO khataiq_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION outbox_mark_published(bigint[])")
    op.execute("DROP FUNCTION outbox_claim(integer)")
