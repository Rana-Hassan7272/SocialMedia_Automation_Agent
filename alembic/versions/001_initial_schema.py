"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.get_table_names():
        return

    from src.database.models import Base
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from src.database.models import Base
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
