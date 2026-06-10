"""Proventos (dividendos/JCP/rendimentos) — tabela incomes.

Revision ID: d3f2a8c1b7e4
Revises: c7a1e9f0d4b2
"""
import sqlalchemy as sa
from alembic import op

revision = 'd3f2a8c1b7e4'
down_revision = 'c7a1e9f0d4b2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'incomes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('asset', sa.String(length=20), nullable=False),
        sa.Column('income_date', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('value', sa.Numeric(18, 6), nullable=False),
        sa.Column('broker', sa.String(length=60), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('incomes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_incomes_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_incomes_asset'), ['asset'], unique=False)
        batch_op.create_index(batch_op.f('ix_incomes_income_date'), ['income_date'], unique=False)


def downgrade():
    with op.batch_alter_table('incomes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_incomes_income_date'))
        batch_op.drop_index(batch_op.f('ix_incomes_asset'))
        batch_op.drop_index(batch_op.f('ix_incomes_user_id'))
    op.drop_table('incomes')
