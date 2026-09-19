"""crm_seven_stages

CRM aşamaları 7 aşamaya indirilir (Yeni Lead, İletişime Geçildi, İlgileniyor, Teklif Gönderildi, Kazanıldı, Takip Bekliyor, Kaybedildi).
Hiçbir kayıt silinmez. Bilgi kaybını önlemek için, birleştirilen eski durumun adı `crm_activities.meta.legacy_stage` içinde saklanır
(ör. 'Ulaşılamadı' → 'İletişime Geçildi' olurken meta.result='Ulaşılamadı' de yazılır).

Revision ID: b7a1c3d5e901
Revises: ac54eca6d6b8
Create Date: 2026-09-19 12:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7a1c3d5e901"
down_revision: Union[str, None] = "ac54eca6d6b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# eski ad → yeni ad (packages/crm.py: LEGACY_STAGE_ALIASES ile aynı; migration kendi kopyasını taşır, kod değişse de geçmiş bozulmaz)
MAPPING = {
    "Yeni": "Yeni Lead", "Takipte": "Takip Bekliyor", "Teklif Verildi": "Teklif Gönderildi", "Müşteri Oldu": "Kazanıldı", "Olumsuz": "Kaybedildi",
    "Yeni Potansiyel": "Yeni Lead", "Aranacak": "Yeni Lead", "Arandı": "İletişime Geçildi", "Görüşüldü": "İletişime Geçildi",
    "Ulaşılamadı": "İletişime Geçildi", "Teklif Hazırlanıyor": "Teklif Gönderildi", "Daha Sonra Ara": "Takip Bekliyor",
}
# iletişim sonucu olarak korunacak eski durumlar
RESULT_FROM_LEGACY = {"Ulaşılamadı": "Ulaşılamadı", "Görüşüldü": "Görüşüldü"}
# downgrade: yeni ad → 12 aşamalı sürümdeki karşılığı (legacy_stage yoksa)
REVERSE = {"Yeni Lead": "Yeni Potansiyel", "İletişime Geçildi": "Arandı"}


def upgrade() -> None:
    conn = op.get_bind()
    for old, new in MAPPING.items():
        # 1) eski adı meta'ya işle (yalnızca gerçekten adı değişen geçişlerde)
        conn.execute(sa.text(
            "UPDATE crm_activities SET meta = coalesce(meta, '{}'::jsonb) || jsonb_build_object('legacy_stage', CAST(:old AS text)) WHERE to_stage = :old"
        ), {"old": old})
        if old in RESULT_FROM_LEGACY:
            conn.execute(sa.text(
                "UPDATE crm_activities SET meta = meta || jsonb_build_object('result', CAST(:res AS text)) WHERE to_stage = :old AND NOT (meta ? 'result')"
            ), {"old": old, "res": RESULT_FROM_LEGACY[old]})
        # 2) adları çevir
        conn.execute(sa.text("UPDATE businesses SET crm_stage = :new WHERE crm_stage = :old"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE crm_activities SET from_stage = :new WHERE from_stage = :old"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE crm_activities SET to_stage = :new WHERE to_stage = :old"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE businesses SET crm_last_action = replace(crm_last_action, :old, :new) WHERE crm_last_action LIKE :pat"),
                     {"old": old, "new": new, "pat": f"%{old}%"})
    conn.execute(sa.text("ALTER TABLE businesses ALTER COLUMN crm_stage SET DEFAULT 'Yeni Lead'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE businesses ALTER COLUMN crm_stage DROP DEFAULT"))
    # aktivite kayıtları: meta.legacy_stage varsa onu, yoksa en yakın 12 aşamalı karşılığı yaz
    conn.execute(sa.text("UPDATE crm_activities SET to_stage = meta->>'legacy_stage' WHERE meta ? 'legacy_stage'"))
    conn.execute(sa.text("UPDATE crm_activities SET meta = meta - 'legacy_stage' WHERE meta ? 'legacy_stage'"))
    for new, old in REVERSE.items():
        conn.execute(sa.text("UPDATE crm_activities SET to_stage = :old WHERE to_stage = :new"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE crm_activities SET from_stage = :old WHERE from_stage = :new"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE businesses SET crm_stage = :old WHERE crm_stage = :new"), {"old": old, "new": new})
