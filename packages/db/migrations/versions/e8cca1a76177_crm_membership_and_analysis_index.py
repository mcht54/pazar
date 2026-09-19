"""CRM üyeliği (businesses.crm_added_at) + analiz geçmişi sorgu indeksleri.

Analiz artık firmayı CRM'e otomatik eklemez: CRM'de olmak `crm_added_at` doluluğuyla ifade edilir. Mevcut kayıtlar KORUNUR;
CRM izi olan firmalar (durumu "Yeni" dışında, notu/geçmişi olan) geriye dönük olarak CRM'e alınır. Hiçbir veri silinmez.

crm_membership_and_analysis_index

Revision ID: e8cca1a76177
Revises: f5973b82f890
Create Date: 2026-09-19 02:55:53.458528

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8cca1a76177'
down_revision: Union[str, None] = 'f5973b82f890'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("businesses", sa.Column("crm_added_at", sa.DateTime(timezone=True), nullable=True))
    # Geriye dönük: CRM izi olan her firma CRM'de sayılır (eklenme zamanı = ilk CRM işlemi ya da son CRM güncellemesi).
    op.execute(
        """
        UPDATE businesses b SET crm_added_at = COALESCE(
            (SELECT min(a.created_at) FROM crm_activities a WHERE a.business_id = b.id),
            b.crm_updated_at,
            now()
        )
        WHERE b.crm_added_at IS NULL AND (
            b.crm_stage <> 'Yeni'
            OR COALESCE(b.staff_note, '') <> ''
            OR b.crm_updated_at IS NOT NULL
            OR EXISTS (SELECT 1 FROM crm_activities a WHERE a.business_id = b.id)
        )
        """
    )
    op.create_index("ix_businesses_crm_added_at", "businesses", ["crm_added_at"])
    op.create_index("ix_crm_activities_business_id", "crm_activities", ["business_id", "created_at"])
    # Analiz sayaçları (bugün/hafta/ay) tamamlanma zamanına göre sorgulanır.
    op.create_index("ix_analysis_jobs_status_completed_at", "analysis_jobs", ["status", "completed_at"])


def downgrade() -> None:
    op.drop_index("ix_analysis_jobs_status_completed_at", table_name="analysis_jobs")
    op.drop_index("ix_crm_activities_business_id", table_name="crm_activities")
    op.drop_index("ix_businesses_crm_added_at", table_name="businesses")
    op.drop_column("businesses", "crm_added_at")
