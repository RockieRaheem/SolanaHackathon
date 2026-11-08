"""Backfill settlement anchors for legacy payment corrections.

Revision ID: e8c4a2f9d731
Revises: d1a6c3f8b902
Create Date: 2026-11-08 16:30:00
"""

import hashlib
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8c4a2f9d731"
down_revision: str | None = "d1a6c3f8b902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    missing = bind.execute(
        sa.text(
            """
            SELECT p.id, p.amount, p.currency, p.external_reference
            FROM payments AS p
            LEFT JOIN settlement_anchors AS anchor ON anchor.payment_id = p.id
            WHERE anchor.id IS NULL
            """
        )
    ).mappings()
    anchors = sa.table(
        "settlement_anchors",
        sa.column("id", sa.Uuid()),
        sa.column("payment_id", sa.Uuid()),
        sa.column("commitment_hash", sa.String(64)),
        sa.column("network", sa.String(32)),
        sa.column("status", sa.String(20)),
    )
    rows = []
    for payment in missing:
        payment_id = payment["id"]
        amount = format(payment["amount"], "f")
        evidence = f"{payment_id}|{amount}|{payment['currency']}|{payment['external_reference']}"
        rows.append(
            {
                "id": uuid.uuid5(uuid.NAMESPACE_URL, f"harambeeone:settlement-anchor:{payment_id}"),
                "payment_id": payment_id,
                "commitment_hash": hashlib.sha256(evidence.encode()).hexdigest(),
                "network": "offchain",
                "status": "backfilled",
            }
        )
    if rows:
        op.bulk_insert(anchors, rows)


def downgrade() -> None:
    op.execute("DELETE FROM settlement_anchors WHERE status = 'backfilled'")
