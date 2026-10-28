"""Add GPS road-learning persistence tables.

Revision ID: 0002_gps_learning
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_gps_learning"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planned_routes",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("ride_id", sa.String(32), nullable=False),
        sa.Column("driver_id", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("segment_ids", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"]),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ride_id", "phase"),
    )
    op.create_index("ix_planned_routes_driver_id", "planned_routes", ["driver_id"])
    op.create_index("ix_planned_routes_ride_id", "planned_routes", ["ride_id"])

    op.create_table(
        "gps_processed_rides",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("ride_id", sa.String(32), nullable=False),
        sa.Column("driver_id", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("vehicle_type", sa.String(16), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"]),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ride_id", "phase"),
    )
    op.create_index(
        "ix_gps_processed_rides_ride_id",
        "gps_processed_rides",
        ["ride_id"],
    )

    op.create_table(
        "gps_road_speed_samples",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("ride_id", sa.String(32), nullable=False),
        sa.Column("driver_id", sa.String(32), nullable=False),
        sa.Column("segment_id", sa.String(128), nullable=False),
        sa.Column("vehicle_type", sa.String(16), nullable=False),
        sa.Column("speed_kmh", sa.Float(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"]),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gps_road_speed_samples_ride_id",
        "gps_road_speed_samples",
        ["ride_id"],
    )
    op.create_index(
        "ix_gps_road_speed_samples_segment_id",
        "gps_road_speed_samples",
        ["segment_id"],
    )

    op.create_table(
        "gps_road_exposures",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("ride_id", sa.String(32), nullable=False),
        sa.Column("driver_id", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("segment_id", sa.String(128), nullable=False),
        sa.Column("vehicle_type", sa.String(16), nullable=False),
        sa.Column("followed", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"]),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ride_id", "phase", "segment_id"),
    )
    op.create_index(
        "ix_gps_road_exposures_ride_id",
        "gps_road_exposures",
        ["ride_id"],
    )
    op.create_index(
        "ix_gps_road_exposures_segment_id",
        "gps_road_exposures",
        ["segment_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gps_road_exposures_segment_id",
        table_name="gps_road_exposures",
    )
    op.drop_index(
        "ix_gps_road_exposures_ride_id",
        table_name="gps_road_exposures",
    )
    op.drop_table("gps_road_exposures")

    op.drop_index(
        "ix_gps_road_speed_samples_segment_id",
        table_name="gps_road_speed_samples",
    )
    op.drop_index(
        "ix_gps_road_speed_samples_ride_id",
        table_name="gps_road_speed_samples",
    )
    op.drop_table("gps_road_speed_samples")

    op.drop_index(
        "ix_gps_processed_rides_ride_id",
        table_name="gps_processed_rides",
    )
    op.drop_table("gps_processed_rides")

    op.drop_index("ix_planned_routes_driver_id", table_name="planned_routes")
    op.drop_index("ix_planned_routes_ride_id", table_name="planned_routes")
    op.drop_table("planned_routes")