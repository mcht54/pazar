"""Çok kullanıcılı giriş, roller, oturumlar, aktivite geçmişi, sistem ayarları; CRM/analiz kayıtlarının kullanıcıya bağlanması.

Güvenli ve EKLEMELİDİR: mevcut hiçbir tablo/satır silinmez veya değiştirilmez. Var olan boş `users` tablosu genişletilir; yeni sütunlar
null/varsayılan değerle eklenir (eski CRM/analiz kayıtlarında kullanıcı bilinmez → boş kalır, uydurulmaz).

auth_users_activity_settings

Revision ID: d80bdca01a17
Revises: e8cca1a76177
Create Date: 2026-09-19 03:33:51.655397

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd80bdca01a17'
down_revision: Union[str, None] = 'e8cca1a76177'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users (var olan boş tablo genişletilir)
    op.add_column("users", sa.Column("username", sa.String(80), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.alter_column("users", "role", server_default="calisan")

    # --- oturumlar
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    # --- personel aktivite geçmişi
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_activity_log_created_at", "activity_log", ["created_at"])
    op.create_index("ix_activity_log_user_created", "activity_log", ["user_id", "created_at"])
    op.create_index("ix_activity_log_action", "activity_log", ["action"])
    op.create_index("ix_activity_log_business", "activity_log", ["business_id"])

    # --- sistem ayarları (Google API vb.; sırlar şifreli)
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )

    # --- CRM'i kullanıcıya bağla (eski kayıtlarda boş kalır)
    op.add_column("businesses", sa.Column("crm_added_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("businesses", sa.Column("crm_updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("businesses", sa.Column("crm_last_action", sa.String(300), nullable=True))
    op.add_column("crm_activities", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))

    # --- analiz geçmişini kullanıcıya bağla; mevcut tüm analiz kayıtları 'user' (personel isteği) sayılmaya devam eder → sayaçlar değişmez
    op.add_column("analysis_jobs", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("analysis_jobs", sa.Column("trigger", sa.String(20), nullable=False, server_default="user"))
    op.create_index("ix_analysis_jobs_user_completed", "analysis_jobs", ["user_id", "completed_at"])
    op.add_column("discovery_jobs", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("discovery_jobs", "user_id")
    op.drop_index("ix_analysis_jobs_user_completed", table_name="analysis_jobs")
    op.drop_column("analysis_jobs", "trigger")
    op.drop_column("analysis_jobs", "user_id")
    op.drop_column("crm_activities", "user_id")
    op.drop_column("businesses", "crm_last_action")
    op.drop_column("businesses", "crm_updated_by")
    op.drop_column("businesses", "crm_added_by")
    op.drop_table("system_settings")
    op.drop_table("activity_log")
    op.drop_table("user_sessions")
    op.alter_column("users", "role", server_default="admin")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    for col in ("updated_at", "locked_until", "failed_login_count", "last_login_at", "must_change_password", "is_active", "password_hash", "username"):
        op.drop_column("users", col)
