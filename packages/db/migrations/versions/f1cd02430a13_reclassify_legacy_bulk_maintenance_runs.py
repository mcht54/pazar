"""Eski toplu YENİDEN HESAPLAMA (bakım) kayıtlarını `trigger='maintenance'` olarak işaretler; analiz sayaçlarında personel analizi gibi sayılmasınlar.

NEDEN: Analiz Raporu, analiz geçmişindeki (analysis_jobs) başarıyla tamamlanmış analizleri sayar. `trigger` sütunu eklenmeden ÖNCE, skor/fırsat kuralları
yayına alındığında tüm firmalar `reanalyze --all` ile önbellekten yeniden hesaplanmıştı; bu toplu işler varsayılan olarak `trigger='user'` kalmış ve
sayaçları şişirmişti (ör. bugün 314 analiz).

BELİRLEME (yalnızca veriye dayalı): kullanıcısı olmayan (user_id boş), `user` tetikli, tamamlanmış/kısmi kayıtlar tamamlanma zamanına göre oturumlara ayrılır
(ardışık kayıtlar arası ≤ 90 sn). Bir oturum ≥ 5 kayıt içeriyor ve dakikada ≥ 20 kayıt hızındaysa bu bir toplu bakım işidir (gerçek araştırma yapan bir analiz
~40 sn sürer, en fazla dakikada ~6 kayıt çıkar).

GÜVENLİ: hiçbir kayıt SİLİNMEZ; yalnızca `trigger` değişir ve stages_status içine {"legacy_reclassified": true} işareti konur. downgrade() bu işaretli
kayıtları birebir geri alır. Analiz geçmişinde bu kayıtlar "Bakım (otomatik)" olarak görünür.

reclassify_legacy_bulk_maintenance_runs

Revision ID: f1cd02430a13
Revises: d80bdca01a17
Create Date: 2026-09-19 04:47:50.111827

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1cd02430a13'
down_revision: Union[str, None] = 'd80bdca01a17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RECLASSIFY_SQL = """
WITH cand AS (
    SELECT id, completed_at,
           CASE WHEN lag(completed_at) OVER w IS NULL OR completed_at - lag(completed_at) OVER w > interval '90 seconds' THEN 1 ELSE 0 END AS new_session
    FROM analysis_jobs
    WHERE trigger = 'user' AND user_id IS NULL AND status IN ('completed', 'partial') AND completed_at IS NOT NULL
    WINDOW w AS (ORDER BY completed_at, id)
), sess AS (
    SELECT id, completed_at, sum(new_session) OVER (ORDER BY completed_at, id) AS sid FROM cand
), agg AS (
    SELECT sid, count(*) AS n, extract(epoch FROM max(completed_at) - min(completed_at)) AS secs FROM sess GROUP BY sid
)
UPDATE analysis_jobs j
SET trigger = 'maintenance', stages_status = j.stages_status || '{"legacy_reclassified": true}'::jsonb
FROM sess s JOIN agg a ON a.sid = s.sid
WHERE j.id = s.id AND a.n >= 5 AND a.n * 60.0 / GREATEST(a.secs, 1) >= 20
"""

REVERT_SQL = """
UPDATE analysis_jobs
SET trigger = 'user', stages_status = stages_status - 'legacy_reclassified'
WHERE stages_status ? 'legacy_reclassified' AND trigger = 'maintenance'
"""


def upgrade() -> None:
    op.execute(RECLASSIFY_SQL)


def downgrade() -> None:
    op.execute(REVERT_SQL)
