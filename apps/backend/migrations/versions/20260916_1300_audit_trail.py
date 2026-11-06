"""Add immutable operational audit trail.

Revision ID: 20260916_1300
Revises: 20260916_0900
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_1300"
down_revision: str | None = "20260916_0900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(120), server_default="system", nullable=False),
        sa.Column("summary", sa.String(240), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_events_school_time", "audit_events", ["school_id", "occurred_at"])
    op.execute('alter table public."audit_events" enable row level security')
    op.execute('revoke all on table public."audit_events" from anon, authenticated')
    op.execute(
        """create function public.capture_audit_event() returns trigger language plpgsql security invoker set search_path = '' as $$ begin insert into public.audit_events (id, school_id, entity_type, entity_id, action, actor, summary) values (gen_random_uuid(), (to_jsonb(new)->>'school_id')::uuid, tg_table_name, new.id, lower(tg_op), 'system', replace(initcap(replace(tg_table_name, '_', ' ')), ' ', ' ') || ' ' || lower(tg_op)); return new; end; $$"""  # noqa: E501
    )
    op.execute(
        "revoke all on function public.capture_audit_event() from public, anon, authenticated"
    )
    for table in (
        "students",
        "fee_structures",
        "payments",
        "statement_imports",
        "statement_transactions",
    ):
        op.execute(
            f'create trigger audit_{table}_insert after insert on public."{table}" for each row execute function public.capture_audit_event()'  # noqa: E501
        )
        op.execute(
            f'create trigger audit_{table}_update after update on public."{table}" for each row execute function public.capture_audit_event()'  # noqa: E501
        )
    op.execute(
        """create function public.protect_audit_event() returns trigger language plpgsql security invoker set search_path = '' as $$ begin raise exception 'Audit events are immutable'; end; $$"""  # noqa: E501
    )
    op.execute(
        "revoke all on function public.protect_audit_event() from public, anon, authenticated"
    )
    op.execute(
        'create trigger protect_audit_events before update or delete on public."audit_events" for each row execute function public.protect_audit_event()'  # noqa: E501
    )


def downgrade() -> None:
    for table in (
        "students",
        "fee_structures",
        "payments",
        "statement_imports",
        "statement_transactions",
    ):
        op.execute(f'drop trigger audit_{table}_insert on public."{table}"')
        op.execute(f'drop trigger audit_{table}_update on public."{table}"')
    op.drop_table("audit_events")
    op.execute("drop function public.capture_audit_event()")
    op.execute("drop function public.protect_audit_event()")
