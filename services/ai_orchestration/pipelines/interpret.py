"""AI yorumlama aşaması (opsiyonel) — Rule Engine'in ürettiği ServiceRecommendation
listesini yorumlar/önceliklendirir. AI_PROVIDER=none iken (varsayılan, API anahtarı
yokken) tamamen atlanır ("skipped") — Finding/ServiceRecommendation/Opportunity
Score bu aşamadan BAĞIMSIZ olarak zaten üretilmiş olur.

Kısıt: AI, rule engine'in üretmediği bir hizmeti öneri listesine EKLEYEMEZ —
bu fonksiyon zaten var olan ServiceRecommendation satırlarının ai_justification
alanını doldurur, yeni service_id icat edemez (kod seviyesinde de yeni satır
oluşturmaz, sadece güncelleme yapar).
"""

from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.models import ServiceRecommendation


def run_ai_interpretation(db: Session, business_id: int, analysis_job_id: int) -> str:
    """Döndürür: 'skipped' | 'success' | 'failed'."""
    if settings.ai_provider != "claude" or not settings.anthropic_api_key:
        return "skipped"

    # Sprint 1 kapsamı dışı: gerçek Claude çağrısı, ANTHROPIC_API_KEY doğrulanınca eklenecek.
    # Not: Bu aşama başarısız olsa/atlansa bile Finding ve ServiceRecommendation
    # kayıtları (rule engine çıktısı) etkilenmez — sistem "AI yoksa hiçbir şey yok"
    # durumuna düşmez.
    recommendations = (
        db.query(ServiceRecommendation)
        .filter_by(business_id=business_id, analysis_job_id=analysis_job_id)
        .all()
    )
    if not recommendations:
        return "skipped"

    raise NotImplementedError("Claude entegrasyonu henüz eklenmedi (ANTHROPIC_API_KEY doğrulanınca yapılacak).")
