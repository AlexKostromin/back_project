"""create cases table and link court_decisions

Revision ID: a13c4be8b932
Revises: 0cdfccfdba0a
Create Date: 2026-04-27 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a13c4be8b932'
down_revision: Union[str, Sequence[str], None] = '0cdfccfdba0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create cases table and add FK from court_decisions."""
    # Create cases table
    op.create_table(
        'cases',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('source_name', sa.String(length=20), nullable=False, comment='Parser source: \'arbitr\', \'sudrf\', etc. Matches court_decisions.source_name'),
        sa.Column('external_id', sa.Text(), nullable=False, comment='External case UUID from source (e.g., KAD CaseId UUID as string)'),
        sa.Column('case_number', sa.Text(), nullable=False, comment='Human-readable case number (e.g., \'А37-1073/2026\'). NOT unique — collisions across courts'),
        sa.Column('court_name', sa.Text(), nullable=False, comment='Full court name (e.g., \'Арбитражный суд города Севастополя\')'),
        sa.Column('court_type', sa.String(length=20), nullable=False, comment='Court type from CourtType enum (arbitrazh, soy, ks, vs, fas)'),
        sa.Column('court_tag', sa.Text(), nullable=True, comment='KAD-specific court routing tag (e.g., \'SEVASTOPOL\'). Used for jurimetric facets'),
        sa.Column('instance_level', sa.Integer(), nullable=False, comment='Court instance level: 1 (first), 2 (appeal), 3 (cassation), 4 (supervisory)'),
        sa.Column('region', sa.Text(), nullable=True, comment='Region extracted from court name (fragile, TZ v1.1 requirement)'),
        sa.Column('dispute_category', sa.Text(), nullable=True, comment='Dispute category from case card <h2> (fragile, KAD-specific)'),
        sa.Column('parties', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False, comment='List of case parties: [{name: str, role: str, inn?: str, ogrn?: str, address?: str}, ...]. PII WARNING: parties[].address contains personal data under 152-ФЗ (natural persons in bankruptcy). Must not appear in unstructured logs or unmasked API responses.'),
        sa.Column('judges', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False, comment='List of judge short names (e.g., [\'Иванов И. И.\', \'Петрова А. Б.\'])'),
        sa.Column('crawled_at', sa.DateTime(timezone=True), nullable=False, comment='Timestamp when the case card was crawled from the source'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('instance_level BETWEEN 1 AND 4', name='ck_cases_instance_level'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_name', 'external_id', name='uq_cases_source_external_id')
    )
    op.create_index(op.f('ix_cases_case_number'), 'cases', ['case_number'], unique=False)
    op.create_index(op.f('ix_cases_court_tag'), 'cases', ['court_tag'], unique=False)

    # Add case_id FK column to search_court_decisions
    op.add_column('search_court_decisions', sa.Column('case_id', sa.BigInteger(), nullable=True, comment='FK to cases table. NULL during migration phase (coexistence period)'))
    op.create_index(op.f('ix_search_court_decisions_case_id'), 'search_court_decisions', ['case_id'], unique=False)
    op.create_foreign_key('fk_search_court_decisions_case_id_cases', 'search_court_decisions', 'cases', ['case_id'], ['id'], ondelete='RESTRICT')


def downgrade() -> None:
    """Drop FK from court_decisions and drop cases table."""
    # Drop FK and column from search_court_decisions
    op.drop_constraint('fk_search_court_decisions_case_id_cases', 'search_court_decisions', type_='foreignkey')
    op.drop_index(op.f('ix_search_court_decisions_case_id'), table_name='search_court_decisions')
    op.drop_column('search_court_decisions', 'case_id')

    # Drop cases table (indexes dropped automatically)
    op.drop_index(op.f('ix_cases_court_tag'), table_name='cases')
    op.drop_index(op.f('ix_cases_case_number'), table_name='cases')
    op.drop_table('cases')
