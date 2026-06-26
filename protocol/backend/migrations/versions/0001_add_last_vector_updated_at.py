"""add last_vector_updated_at to users

Revision ID: 0001_add_last_vector_updated_at
Revises: 
Create Date: 2026-05-22 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_add_last_vector_updated_at'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add nullable timestamp column to users for vector decay bookkeeping
    op.add_column('users', sa.Column('last_vector_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('users', 'last_vector_updated_at')
