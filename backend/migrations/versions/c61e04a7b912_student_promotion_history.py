"""student promotion history

Revision ID: c61e04a7b912
Revises: a245db0fddf9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c61e04a7b912"
down_revision: Union[str, Sequence[str], None] = "a245db0fddf9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "student_promotions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "student_promotions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_year_id", sa.Uuid(), nullable=False),
        sa.Column("target_year_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("from_section", sa.String(length=120), nullable=False),
        sa.Column("to_section", sa.String(length=120), nullable=True),
        sa.Column("applied_by", sa.Uuid(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["applied_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_year_id"], ["academic_years.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.ForeignKeyConstraint(["target_year_id"], ["academic_years.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_year_id", "student_id", name="uq_promotion_source_student"),
    )
    for column in ("source_year_id", "target_year_id", "student_id", "action", "applied_by"):
        op.create_index(f"ix_student_promotions_{column}", "student_promotions", [column], unique=False)


def downgrade() -> None:
    if "student_promotions" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("student_promotions")
