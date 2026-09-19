"""sales_pipeline_stages_prices_reset_tokens

12 aşamalı satış hunisi (eski durum adları veri kaybı olmadan yeniden adlandırılır), CRM'e satış takibi alanları,
hizmet fiyat aralıkları (service_prices), şifre belirleme/sıfırlama belirteçleri (password_reset_tokens) ve sorgu indeksleri.

Revision ID: ac54eca6d6b8
Revises: f1cd02430a13
Create Date: 2026-09-19 05:05:14.836330

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ac54eca6d6b8"
down_revision: Union[str, None] = "f1cd02430a13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# eski ad -> yeni ad (12 aşamalı huni). Downgrade bunun tersini uygular.
RENAMES = {
    "Yeni": "Yeni Potansiyel",
    "Takipte": "Takip Bekliyor",
    "Teklif Verildi": "Teklif Gönderildi",
    "Müşteri Oldu": "Kazanıldı",
    "Olumsuz": "Kaybedildi",
}


def _rename(mapping: dict[str, str]) -> None:
    for old, new in mapping.items():
        op.execute(sa.text("UPDATE businesses SET crm_stage = :new WHERE crm_stage = :old").bindparams(old=old, new=new))
        op.execute(sa.text("UPDATE crm_activities SET from_stage = :new WHERE from_stage = :old").bindparams(old=old, new=new))
        op.execute(sa.text("UPDATE crm_activities SET to_stage = :new WHERE to_stage = :old").bindparams(old=old, new=new))
        op.execute(sa.text("UPDATE businesses SET crm_last_action = replace(crm_last_action, :old, :new) WHERE crm_last_action LIKE :pat").bindparams(old=old, new=new, pat=f"%{old}%"))


def upgrade() -> None:
    # --- businesses: satış takibi alanları (hepsi boş olabilir; mevcut veri değişmez)
    op.add_column("businesses", sa.Column("crm_owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("businesses", sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("businesses", sa.Column("follow_up_note", sa.Text(), nullable=True))
    op.add_column("businesses", sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("businesses", sa.Column("interested_service", sa.String(120), nullable=True))
    op.add_column("businesses", sa.Column("offer_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("businesses", sa.Column("sale_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("businesses", sa.Column("lost_reason", sa.String(300), nullable=True))
    op.add_column("crm_activities", sa.Column("meta", postgresql.JSONB(), nullable=True))

    # --- mevcut kayıtlar: sorumlu = ekleyen (gerçek kayıt), son görüşme = gerçek arama/görüşme etkinliği
    op.execute("UPDATE businesses SET crm_owner_id = crm_added_by WHERE crm_added_at IS NOT NULL AND crm_added_by IS NOT NULL")
    op.execute(
        """
        UPDATE businesses b SET last_contact_at = s.last_at
        FROM (SELECT business_id, max(created_at) AS last_at FROM crm_activities
              WHERE to_stage IN ('Arandı', 'Görüşüldü') OR type IN ('call', 'meeting') GROUP BY business_id) s
        WHERE s.business_id = b.id
        """
    )

    # --- durum adları: 12 aşamalı huni (eski adlar korunarak eşlenir)
    _rename(RENAMES)

    # --- hizmet fiyat aralıkları: kodda sabit fiyat YOK; yönetici girer
    op.create_table(
        "service_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services_catalog.id"), nullable=False, unique=True),
        sa.Column("min_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("max_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("default_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- şifre belirleme / sıfırlama belirteçleri (yalnızca SHA-256 özeti saklanır)
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("purpose", sa.String(20), nullable=False, server_default="reset"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])

    # --- indeksler
    op.create_index("ix_businesses_crm_stage", "businesses", ["crm_stage"])
    op.create_index("ix_businesses_next_follow_up_at", "businesses", ["next_follow_up_at"], postgresql_where=sa.text("next_follow_up_at IS NOT NULL"))
    op.create_index("ix_businesses_crm_owner_id", "businesses", ["crm_owner_id"])
    op.create_index("ix_analysis_jobs_business_id", "analysis_jobs", ["business_id", "completed_at"])
    op.create_index("ix_crm_activities_user_created", "crm_activities", ["user_id", "created_at"])
    op.create_index("ix_crm_activities_to_stage", "crm_activities", ["to_stage", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_crm_activities_to_stage", table_name="crm_activities")
    op.drop_index("ix_crm_activities_user_created", table_name="crm_activities")
    op.drop_index("ix_analysis_jobs_business_id", table_name="analysis_jobs")
    op.drop_index("ix_businesses_crm_owner_id", table_name="businesses")
    op.drop_index("ix_businesses_next_follow_up_at", table_name="businesses")
    op.drop_index("ix_businesses_crm_stage", table_name="businesses")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_table("service_prices")
    # yeni aşamalar eski huniye eşlenemez: en yakın eski ada indirilir
    op.execute("UPDATE businesses SET crm_stage = 'Arandı' WHERE crm_stage IN ('İlgileniyor', 'Ulaşılamadı')")
    op.execute("UPDATE businesses SET crm_stage = 'Görüşüldü' WHERE crm_stage = 'Teklif Hazırlanıyor'")
    _rename({new: old for old, new in RENAMES.items()})
    op.drop_column("crm_activities", "meta")
    for col in ("lost_reason", "sale_amount", "offer_amount", "interested_service", "last_contact_at", "follow_up_note", "next_follow_up_at", "crm_owner_id"):
        op.drop_column("businesses", col)
