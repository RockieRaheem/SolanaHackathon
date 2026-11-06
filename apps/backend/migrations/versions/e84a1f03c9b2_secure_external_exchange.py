"""add secure external exchange

Revision ID: e84a1f03c9b2
Revises: d719a24c6e31
Create Date: 2026-10-22 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e84a1f03c9b2"
down_revision: str | None = "d719a24c6e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_clients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(20), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column("allowed_fields_json", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(240), nullable=False),
        sa.Column("lawful_basis", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), server_default="60", nullable=False),
        sa.Column("request_window_started_at", sa.DateTime(timezone=True)),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.String(254), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("school_id", "name", name="uq_integration_clients_school_name"),
        sa.CheckConstraint("status in ('active','revoked')", name="ck_integration_clients_status"),
    )
    op.create_index("ix_integration_clients_school_id", "integration_clients", ["school_id"])
    op.create_index(
        "ix_integration_clients_key_prefix", "integration_clients", ["key_prefix"], unique=True
    )

    op.create_table(
        "integration_webhook_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "integration_client_id",
            sa.Uuid(),
            sa.ForeignKey("integration_clients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("signing_secret", sa.String(96), nullable=False),
        sa.Column("event_types_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_by", sa.String(254), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("integration_client_id", "url", name="uq_integration_webhooks_url"),
        sa.CheckConstraint(
            "status in ('active','disabled')", name="ck_integration_webhooks_status"
        ),
    )
    op.create_index(
        "ix_integration_webhook_subscriptions_school_id",
        "integration_webhook_subscriptions",
        ["school_id"],
    )
    op.create_index(
        "ix_integration_webhook_subscriptions_integration_client_id",
        "integration_webhook_subscriptions",
        ["integration_client_id"],
    )

    op.create_table(
        "integration_outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(40), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_integration_outbox_events_school_id", "integration_outbox_events", ["school_id"]
    )
    op.create_index(
        "ix_integration_outbox_events_aggregate_id", "integration_outbox_events", ["aggregate_id"]
    )
    op.create_index(
        "ix_integration_outbox_events_correlation_id",
        "integration_outbox_events",
        ["correlation_id"],
    )
    op.create_index(
        "ix_integration_outbox_school_created",
        "integration_outbox_events",
        ["school_id", "created_at"],
    )

    op.create_table(
        "integration_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("integration_outbox_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.Uuid(),
            sa.ForeignKey("integration_webhook_subscriptions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_response_code", sa.Integer()),
        sa.Column("last_error", sa.String(500)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "event_id", "subscription_id", name="uq_integration_delivery_event_hook"
        ),
        sa.CheckConstraint(
            "status in ('pending','delivered','failed','abandoned')",
            name="ck_integration_deliveries_status",
        ),
    )
    op.create_index("ix_integration_deliveries_school_id", "integration_deliveries", ["school_id"])
    op.create_index("ix_integration_deliveries_event_id", "integration_deliveries", ["event_id"])
    op.create_index(
        "ix_integration_deliveries_subscription_id", "integration_deliveries", ["subscription_id"]
    )
    op.create_index(
        "ix_integration_deliveries_school_status", "integration_deliveries", ["school_id", "status"]
    )

    op.create_table(
        "integration_exchange_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "integration_client_id",
            sa.Uuid(),
            sa.ForeignKey("integration_clients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(12), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(240), nullable=False),
        sa.Column("lawful_basis", sa.String(120), nullable=False),
        sa.Column("fields_json", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(100)),
        sa.Column("record_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("detail", sa.String(500)),
        sa.Column("actor", sa.String(254), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "direction in ('export','import')", name="ck_integration_exchange_direction"
        ),
    )
    op.create_index(
        "ix_integration_exchange_logs_school_id", "integration_exchange_logs", ["school_id"]
    )
    op.create_index(
        "ix_integration_exchange_logs_integration_client_id",
        "integration_exchange_logs",
        ["integration_client_id"],
    )
    op.create_index(
        "ix_integration_exchange_logs_correlation_id",
        "integration_exchange_logs",
        ["correlation_id"],
    )
    op.create_index(
        "ix_integration_exchange_school_created",
        "integration_exchange_logs",
        ["school_id", "created_at"],
    )

    op.create_table(
        "integration_import_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "integration_client_id",
            sa.Uuid(),
            sa.ForeignKey("integration_clients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("issues_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("record_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("reviewed_by", sa.String(254)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "integration_client_id", "idempotency_key", name="uq_integration_import_client_key"
        ),
        sa.CheckConstraint(
            "status in ('validated','quarantined','acknowledged','rejected')",
            name="ck_integration_import_status",
        ),
    )
    op.create_index(
        "ix_integration_import_batches_school_id", "integration_import_batches", ["school_id"]
    )
    op.create_index(
        "ix_integration_import_batches_integration_client_id",
        "integration_import_batches",
        ["integration_client_id"],
    )
    op.create_index(
        "ix_integration_import_school_status", "integration_import_batches", ["school_id", "status"]
    )

    tables = (
        "integration_clients",
        "integration_webhook_subscriptions",
        "integration_outbox_events",
        "integration_deliveries",
        "integration_exchange_logs",
        "integration_import_batches",
    )
    for table in tables:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
    for table in tables:
        op.execute(
            f"""
            CREATE POLICY {table}_owner_access ON public.{table}
            FOR ALL TO authenticated USING (
                private.has_school_role(school_id, ARRAY['owner']::text[])
            ) WITH CHECK (
                private.has_school_role(school_id, ARRAY['owner']::text[])
            )
            """
        )


def downgrade() -> None:
    for table in (
        "integration_import_batches",
        "integration_exchange_logs",
        "integration_deliveries",
        "integration_outbox_events",
        "integration_webhook_subscriptions",
        "integration_clients",
    ):
        op.drop_table(table)
