"""offer_snapshots

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-11

"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6g7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offer_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fuente", sa.String(255), nullable=False),
        sa.Column("snapped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_activas", sa.Integer(), nullable=False),
        sa.Column("precio_min", sa.Float(), nullable=True),
        sa.Column("precio_avg", sa.Float(), nullable=True),
        sa.Column("precio_max", sa.Float(), nullable=True),
        sa.Column("descuento_avg", sa.Float(), nullable=True),
        sa.Column("descuento_max", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_offer_snapshots_fuente", "offer_snapshots", ["fuente"])
    op.create_index("ix_offer_snapshots_snapped_at", "offer_snapshots", ["snapped_at"])

    # Seed with current data
    op.execute("""
        INSERT INTO offer_snapshots
            (fuente, snapped_at, total_activas,
             precio_min, precio_avg, precio_max, descuento_avg, descuento_max)
        SELECT fuente, now(), count(*),
               min(precio_oferta), avg(precio_oferta), max(precio_oferta),
               avg(descuento_porcentaje), max(descuento_porcentaje)
        FROM ofertas
        WHERE activo = true
        GROUP BY fuente
    """)


def downgrade() -> None:
    op.drop_index("ix_offer_snapshots_snapped_at", table_name="offer_snapshots")
    op.drop_index("ix_offer_snapshots_fuente", table_name="offer_snapshots")
    op.drop_table("offer_snapshots")
