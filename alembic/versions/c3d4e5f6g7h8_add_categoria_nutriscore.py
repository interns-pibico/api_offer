"""add categoria nutriscore novascore columns

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-03-18 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3d4e5f6g7h8"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ofertas", sa.Column("categoria", sa.String(50), nullable=True))
    op.add_column("ofertas", sa.Column("nutriscore", sa.String(1), nullable=True))
    op.add_column("ofertas", sa.Column("novascore", sa.SmallInteger(), nullable=True))
    op.create_index(op.f("ix_ofertas_categoria"), "ofertas", ["categoria"])
    op.create_index(op.f("ix_ofertas_nutriscore"), "ofertas", ["nutriscore"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ofertas_nutriscore"), table_name="ofertas")
    op.drop_index(op.f("ix_ofertas_categoria"), table_name="ofertas")
    op.drop_column("ofertas", "novascore")
    op.drop_column("ofertas", "nutriscore")
    op.drop_column("ofertas", "categoria")
