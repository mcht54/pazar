"""crm_nine_stages

CRM durumları 9 aşamaya sabitlenir: Yeni, Aranacak, Daha Sonra Ara, Arandı, Görüşüldü, Teklif Gönderildi, Takip Bekliyor, Kazanıldı, Kaybedildi.
Hiçbir kayıt silinmez. Eski adlar dönüştürülür (Teklif Verildi→Teklif Gönderildi, Takipte→Takip Bekliyor, Müşteri Oldu→Kazanıldı, Olumsuz→Kaybedildi) ve
7 aşamalı ara sürümde birleştirilmiş kayıtlar, `crm_activities.meta.legacy_stage` bilgisiyle ÖZGÜN durumlarına geri döndürülür (Aranacak, Görüşüldü, Daha Sonra Ara …).

Revision ID: e6f0a4b8c334
Revises: d5e9f3a7b223
Create Date: 2026-09-19 16:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e6f0a4b8c334"
down_revision: Union[str, None] = "d5e9f3a7b223"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW = ("Yeni", "Aranacak", "Daha Sonra Ara", "Arandı", "Görüşüldü", "Teklif Gönderildi", "Takip Bekliyor", "Kazanıldı", "Kaybedildi")
# eski/ara ad → yeni ad (kalan kayıtlar için varsayılan eşleme)
MAPPING = {
    "Teklif Verildi": "Teklif Gönderildi", "Takipte": "Takip Bekliyor", "Müşteri Oldu": "Kazanıldı", "Olumsuz": "Kaybedildi",
    "Yeni Lead": "Yeni", "Yeni Potansiyel": "Yeni", "İletişime Geçildi": "Arandı", "Ulaşılamadı": "Arandı", "İlgileniyor": "Görüşüldü",
    "Teklif Hazırlanıyor": "Teklif Gönderildi",
}
# downgrade: 9 aşamalı ad → 7 aşamalı ara sürümdeki karşılığı
DOWN = {"Yeni": "Yeni Lead", "Aranacak": "Yeni Lead", "Daha Sonra Ara": "Takip Bekliyor", "Arandı": "İletişime Geçildi", "Görüşüldü": "İlgileniyor"}


def _in_list(names) -> str:
    return ", ".join("'" + n.replace("'", "''") + "'" for n in names)


def upgrade() -> None:
    conn = op.get_bind()
    # 1) 7 aşamalı sürümde birleştirilen firmalar: son geçiş kaydındaki özgün adı (legacy_stage) geçerliyse geri getir
    conn.execute(sa.text(f"""
        UPDATE businesses b SET crm_stage = a.meta->>'legacy_stage'
        FROM (
            SELECT DISTINCT ON (business_id) business_id, to_stage, meta
            FROM crm_activities WHERE type IN ('added', 'status_change', 'contact')
            ORDER BY business_id, created_at DESC, id DESC
        ) a
        WHERE a.business_id = b.id AND a.meta ? 'legacy_stage' AND a.to_stage = b.crm_stage AND a.meta->>'legacy_stage' IN ({_in_list(NEW)})
    """))
    # 2) aktivite kayıtlarında özgün adı geri getir
    conn.execute(sa.text(f"""
        UPDATE crm_activities SET to_stage = meta->>'legacy_stage', meta = meta - 'legacy_stage'
        WHERE meta ? 'legacy_stage' AND meta->>'legacy_stage' IN ({_in_list(NEW)})
    """))
    # 3) kalan eski adlar
    for old, new in MAPPING.items():
        conn.execute(sa.text("UPDATE businesses SET crm_stage = :new WHERE crm_stage = :old"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE crm_activities SET from_stage = :new WHERE from_stage = :old"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE crm_activities SET to_stage = :new WHERE to_stage = :old"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE businesses SET crm_last_action = replace(crm_last_action, :old, :new) WHERE crm_last_action LIKE :pat"),
                     {"old": old, "new": new, "pat": f"%{old}%"})
    conn.execute(sa.text("ALTER TABLE businesses ALTER COLUMN crm_stage SET DEFAULT 'Yeni'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE businesses ALTER COLUMN crm_stage SET DEFAULT 'Yeni Lead'"))
    for new, old in DOWN.items():
        # özgün adı meta'ya işle (7 aşamalı sürümün beklediği biçim), sonra adı çevir
        conn.execute(sa.text("UPDATE crm_activities SET meta = coalesce(meta, '{}'::jsonb) || jsonb_build_object('legacy_stage', CAST(:new AS text)) WHERE to_stage = :new"), {"new": new})
        conn.execute(sa.text("UPDATE businesses SET crm_stage = :old WHERE crm_stage = :new"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE crm_activities SET from_stage = :old WHERE from_stage = :new"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE crm_activities SET to_stage = :old WHERE to_stage = :new"), {"old": old, "new": new})
