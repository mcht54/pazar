"""user_analyses_follow_ups_indexes

- user_analyses: kullanıcı bazlı analiz geçmişi (unique user_id + business_id + analysis_type). Mevcut `analysis_jobs` kayıtlarından (yalnızca kullanıcısı BİLİNEN ve
  başarıyla tamamlanan, bakım olmayan analizler) doldurulur. Kullanıcısı bilinmeyen eski analizler hiçbir kullanıcıya atfedilmez.
- follow_ups: takipler (tarih + saat + not + durum). Mevcut `businesses.next_follow_up_at` değerleri 'Bekliyor' takip olarak taşınır (silinmez; alan önbellek olarak kalır).
- Liste/filtre sorguları için indeksler.

Revision ID: c4d8e2f6a112
Revises: b7a1c3d5e901
Create Date: 2026-09-19 13:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c4d8e2f6a112"
down_revision: Union[str, None] = "b7a1c3d5e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("analysis_type", sa.String(30), nullable=False, server_default="deep"),
        sa.Column("analysis_job_id", sa.Integer(), sa.ForeignKey("analysis_jobs.id"), nullable=True),
        sa.Column("analysis_result", postgresql.JSONB(), nullable=True),
        sa.Column("runs", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "business_id", "analysis_type", name="uq_user_analysis"),
    )
    op.create_index("ix_user_analyses_business_id", "user_analyses", ["business_id"])
    # geri doldurma: her (kullanıcı, işletme) için ilk/son başarılı analiz ve sayı
    op.execute(
        """
        INSERT INTO user_analyses (user_id, business_id, analysis_type, analysis_job_id, analysis_result, runs, created_at, updated_at)
        SELECT j.user_id, j.business_id, 'deep',
               (array_agg(j.id ORDER BY j.completed_at DESC, j.id DESC))[1],
               jsonb_build_object('status', 'completed', 'backfilled', true),
               count(*), min(j.completed_at), max(j.completed_at)
        FROM analysis_jobs j
        WHERE j.status = 'completed' AND j.trigger = 'user' AND j.user_id IS NOT NULL AND j.completed_at IS NOT NULL
        GROUP BY j.user_id, j.business_id
        """
    )

    op.create_table(
        "follow_ups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("has_time", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="Bekliyor"),
        sa.Column("result", sa.String(60), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_follow_ups_business_status", "follow_ups", ["business_id", "status"])
    op.create_index("ix_follow_ups_pending_due", "follow_ups", ["due_at"], postgresql_where=sa.text("status = 'Bekliyor'"))
    op.create_index("ix_follow_ups_user_status_due", "follow_ups", ["user_id", "status", "due_at"])
    # mevcut takipler taşınır (saat bilgisi yoksa yalnızca gün)
    op.execute(
        """
        INSERT INTO follow_ups (business_id, user_id, created_by, due_at, has_time, note, status)
        SELECT id, coalesce(crm_owner_id, crm_updated_by), crm_updated_by, next_follow_up_at,
               (next_follow_up_at AT TIME ZONE 'Europe/Istanbul')::time <> time '00:00', follow_up_note, 'Bekliyor'
        FROM businesses WHERE next_follow_up_at IS NOT NULL AND crm_added_at IS NOT NULL
        """
    )

    # liste/filtre indeksleri
    op.create_index("ix_businesses_region_sector", "businesses", ["region_id", "sector_id"])
    op.create_index("ix_businesses_sector_id", "businesses", ["sector_id"])
    op.create_index("ix_businesses_status", "businesses", ["status"])
    op.create_index("ix_businesses_created_at", "businesses", ["created_at"])
    op.create_index("ix_businesses_last_analysis_at", "businesses", ["last_analysis_at"])
    op.create_index("ix_businesses_sales_priority", "businesses", ["sales_priority"])
    op.create_index("ix_businesses_category_label", "businesses", ["category_label"])
    op.create_index("ix_sales_assessments_business_id", "sales_assessments", ["business_id", "id"])
    op.create_index("ix_discovery_job_results_business_id", "discovery_job_results", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_discovery_job_results_business_id", table_name="discovery_job_results")
    op.drop_index("ix_sales_assessments_business_id", table_name="sales_assessments")
    for name in ("category_label", "sales_priority", "last_analysis_at", "created_at", "status", "sector_id"):
        op.drop_index(f"ix_businesses_{name}", table_name="businesses")
    op.drop_index("ix_businesses_region_sector", table_name="businesses")
    op.drop_index("ix_follow_ups_user_status_due", table_name="follow_ups")
    op.drop_index("ix_follow_ups_pending_due", table_name="follow_ups")
    op.drop_index("ix_follow_ups_business_status", table_name="follow_ups")
    op.drop_table("follow_ups")
    op.drop_index("ix_user_analyses_business_id", table_name="user_analyses")
    op.drop_table("user_analyses")
