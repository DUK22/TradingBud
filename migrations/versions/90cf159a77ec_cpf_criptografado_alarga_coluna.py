"""cpf criptografado (alarga coluna)

Revision ID: 90cf159a77ec
Revises: fb65ad5371e5
Create Date: 2026-06-05 02:32:00.030987

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '90cf159a77ec'
down_revision = 'fb65ad5371e5'
branch_labels = None
depends_on = None


def upgrade():
    # CPF passa a ser criptografado (EncryptedString); no banco é apenas um
    # texto maior, então alargamos a coluna de 14 para 255.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('cpf',
               existing_type=sa.VARCHAR(length=14),
               type_=sa.String(length=255),
               existing_nullable=True)


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('cpf',
               existing_type=sa.String(length=255),
               type_=sa.VARCHAR(length=14),
               existing_nullable=True)
