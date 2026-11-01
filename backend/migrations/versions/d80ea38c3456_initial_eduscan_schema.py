"""initial eduscan schema

Revision ID: d80ea38c3456
Revises:
Create Date: 2026-08-21 08:25:46.104868

"""
from typing import Sequence, Union

from alembic import op
from app.database import Base
from app import models  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = 'd80ea38c3456'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Downgrade schema."""
    Base.metadata.drop_all(bind=op.get_bind())
