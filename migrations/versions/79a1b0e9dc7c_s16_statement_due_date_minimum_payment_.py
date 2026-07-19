"""S16 statement due_date + minimum_payment for bill card

Revision ID: 79a1b0e9dc7c
Revises: 741f49a1c0c3
Create Date: 2026-07-19 15:12:24.546783

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79a1b0e9dc7c'
down_revision: Union[str, Sequence[str], None] = '741f49a1c0c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Credit-card bill summary for the §3.4 due-date aggregator card. Both nullable:
    # non-CC statements carry neither, and existing rows predate the columns. The persist
    # stage (pipeline) populates them from the parsed CC summary.
    op.add_column("statement", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column(
        "statement",
        sa.Column("minimum_payment", sa.Numeric(precision=18, scale=2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("statement", "minimum_payment")
    op.drop_column("statement", "due_date")
