"""align court_decisions with v1.1 contract: add crawled_at/parsed_at, tighten nullability

Revision ID: 0cdfccfdba0a
Revises: ca22895b531d
Create Date: 2026-04-23 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0cdfccfdba0a'
down_revision: Union[str, Sequence[str], None] = 'ca22895b531d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add crawled_at and parsed_at columns
    op.add_column('search_court_decisions', sa.Column('crawled_at', sa.DateTime(timezone=True), nullable=False))
    op.add_column('search_court_decisions', sa.Column('parsed_at', sa.DateTime(timezone=True), nullable=False))

    # Tighten nullability constraints
    op.alter_column('search_court_decisions', 'instance_level',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.alter_column('search_court_decisions', 'result',
               existing_type=sa.VARCHAR(length=30),
               nullable=False)
    op.alter_column('search_court_decisions', 'appeal_status',
               existing_type=sa.VARCHAR(length=30),
               nullable=False,
               server_default=sa.text("'none'"))
    op.alter_column('search_court_decisions', 'dispute_type',
               existing_type=sa.VARCHAR(length=30),
               nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Revert nullability constraints
    op.alter_column('search_court_decisions', 'dispute_type',
               existing_type=sa.VARCHAR(length=30),
               nullable=True)
    op.alter_column('search_court_decisions', 'appeal_status',
               existing_type=sa.VARCHAR(length=30),
               nullable=True,
               server_default=None)
    op.alter_column('search_court_decisions', 'result',
               existing_type=sa.VARCHAR(length=30),
               nullable=True)
    op.alter_column('search_court_decisions', 'instance_level',
               existing_type=sa.INTEGER(),
               nullable=True)

    # Remove crawled_at and parsed_at columns
    op.drop_column('search_court_decisions', 'parsed_at')
    op.drop_column('search_court_decisions', 'crawled_at')
