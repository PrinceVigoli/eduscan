"""Add student sex for SF4 male/female reporting."""
from alembic import op
import sqlalchemy as sa

revision = "e42b81c0fa63"
down_revision = "c61e04a7b912"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("students")}
    if "sex" not in columns:
        op.add_column("students", sa.Column("sex", sa.String(6), nullable=True))


def downgrade():
    op.drop_column("students", "sex")
