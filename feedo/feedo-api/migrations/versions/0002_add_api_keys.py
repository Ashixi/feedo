"""add api_keys table

Revision ID: 0002_add_api_keys
Revises: 0001_add_last_vector_updated_at
Create Date: 2026-05-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0002_add_api_keys'
down_revision = '0001_add_last_vector_updated_at'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'api_keys',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('hashed_key', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='developer'),
        sa.Column('owner_address', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=True, server_default=sa.text('false')),
        sa.Column('rate_limit_bucket', sa.JSON(), nullable=True)
    )
    op.create_index(op.f('ix_api_keys_owner_address'), 'api_keys', ['owner_address'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_api_keys_owner_address'), table_name='api_keys')
    op.drop_table('api_keys')
