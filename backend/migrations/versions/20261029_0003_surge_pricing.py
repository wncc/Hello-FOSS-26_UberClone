"""Store the surge multiplier on each ride."""
from alembic import op
import sqlalchemy as sa

revision = "0003_surge_pricing"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rides") as batch_op:
        batch_op.add_column(
            sa.Column(
                "surge_multiplier",
                sa.Float(),
                nullable=False,
                server_default="1.0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("rides") as batch_op:
        batch_op.drop_column("surge_multiplier")

