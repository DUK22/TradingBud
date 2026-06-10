"""Eventos corporativos (position_adjustments) e e-mail verificado no usuário.

Revision ID: c7a1e9f0d4b2
Revises: b110654c9410
"""
import sqlalchemy as sa
from alembic import op

revision = 'c7a1e9f0d4b2'
down_revision = 'b110654c9410'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'position_adjustments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('asset', sa.String(length=20), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('factor', sa.Numeric(18, 6), nullable=True),
        sa.Column('qty', sa.Numeric(18, 6), nullable=True),
        sa.Column('price', sa.Numeric(18, 6), nullable=True),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('position_adjustments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_position_adjustments_user_id'),
                              ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_position_adjustments_asset'),
                              ['asset'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_verified', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('email_verified')
    with op.batch_alter_table('position_adjustments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_position_adjustments_asset'))
        batch_op.drop_index(batch_op.f('ix_position_adjustments_user_id'))
    op.drop_table('position_adjustments')
