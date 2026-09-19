"""session_remember

user_sessions.remember: 'Beni hatırla' işaretli mi (kalıcı çerez + daha uzun kayan süre). Mevcut oturumlar false kalır (davranış değişmez).

Revision ID: d5e9f3a7b223
Revises: c4d8e2f6a112
Create Date: 2026-09-19 13:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d5e9f3a7b223"
down_revision: Union[str, None] = "c4d8e2f6a112"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_sessions", sa.Column("remember", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("user_sessions", "remember")
