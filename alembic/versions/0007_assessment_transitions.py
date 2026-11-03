"""Assessment state machine enforced in the database.

    draft -> in_review -> approved | rejected
    in_review -> draft
    approved and rejected are final.

The service checks transitions first (and answers 409); this trigger makes the rule hold for
any writer, including a bug or a hand-written SQL statement.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION check_assessment_transition() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (OLD.status, NEW.status) NOT IN (
                ('draft'::assessment_status, 'in_review'::assessment_status),
                ('in_review', 'draft'),
                ('in_review', 'approved'),
                ('in_review', 'rejected')
            ) THEN
                RAISE EXCEPTION 'illegal assessment transition % -> %', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER assessment_transition
        BEFORE UPDATE OF status ON assessments
        FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
        EXECUTE FUNCTION check_assessment_transition()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER assessment_transition ON assessments")
    op.execute("DROP FUNCTION check_assessment_transition()")
