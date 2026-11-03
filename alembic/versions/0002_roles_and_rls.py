"""App role and row-level security.

* khataiq_app is the role the API and workers connect as. It is not the table owner and has no
  BYPASSRLS, so the policies below always apply to it.
* Every tenant table gets RLS with one policy: org_id = app_org_id(), where app_org_id() reads
  the transaction-local setting app.org_id (set by khataiq.db.tenant_session). Unset -> NULL ->
  no rows visible and no rows insertable.
* Append-only tables (audit_log, txn_labels, evidence_links, metric tables) get SELECT and
  INSERT only.
* Login must find a user by email before the tenant is known; auth_find_user() is a narrow
  SECURITY DEFINER function for exactly that, instead of exempting users from RLS.
* Downgrade revokes everything but does not drop the role: roles are cluster-wide and another
  database in the same cluster (dev vs test) may still have objects granted to it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "khataiq_app"

# Tables the app may read and change.
READ_WRITE = [
    "users", "businesses", "accounts", "uploads", "idempotency_keys", "outbox",
    "pipeline_runs", "transactions", "flags", "flag_evidence", "assessments",
]
# Tables the app may only read and append to.
APPEND_ONLY = ["audit_log", "txn_labels", "evidence_links", "metric_runs", "monthly_metrics"]
TENANT_TABLES = READ_WRITE + APPEND_ONLY


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END $$
    """)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")

    op.execute("""
        CREATE FUNCTION app_org_id() RETURNS bigint
        LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.org_id', true), '')::bigint $$
    """)

    op.execute(f"GRANT SELECT ON organizations TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(READ_WRITE)} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {', '.join(APPEND_ONLY)} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")

    # Views run with their owner's rights by default, which would skip RLS on txn_labels.
    op.execute("ALTER VIEW current_txn_labels SET (security_invoker = true)")
    op.execute(f"GRANT SELECT ON current_txn_labels TO {APP_ROLE}")

    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON organizations TO {APP_ROLE}
        USING (id = app_org_id())
    """)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table} TO {APP_ROLE}
            USING (org_id = app_org_id())
            WITH CHECK (org_id = app_org_id())
        """)

    op.execute("""
        CREATE FUNCTION auth_find_user(p_email text)
        RETURNS TABLE (id bigint, org_id bigint, password_hash text, role user_role,
                       is_active boolean)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT u.id, u.org_id, u.password_hash::text, u.role, u.is_active
            FROM users u WHERE u.email = lower(p_email)
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION auth_find_user(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_find_user(text) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION auth_find_user(text)")
    for table in ["organizations", *TENANT_TABLES]:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON current_txn_labels FROM {APP_ROLE}")
    op.execute("ALTER VIEW current_txn_labels RESET (security_invoker)")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute("DROP FUNCTION app_org_id()")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
