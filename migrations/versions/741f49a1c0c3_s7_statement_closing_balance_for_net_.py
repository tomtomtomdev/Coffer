"""S7 statement.closing_balance for net-worth grid

Revision ID: 741f49a1c0c3
Revises: 1764a988dedb
Create Date: 2026-07-14 20:11:29.875782

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '741f49a1c0c3'
down_revision: Union[str, Sequence[str], None] = '1764a988dedb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # The account's net-worth value as of the statement (SPEC §3.1 carry-forward).
    # Nullable: existing rows carry no balance; the persist stage (S9) populates it.
    op.add_column(
        "statement",
        sa.Column("closing_balance", sa.Numeric(precision=18, scale=2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("statement", "closing_balance")
