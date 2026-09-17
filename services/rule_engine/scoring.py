"""Boyut bazlı Opportunity Score hesaplama — tek bir gizemli skor YOK.

Her dimension (web/seo/google_visibility/social/ads/design/print) için:
- o kategoride hiç finding/metrik yoksa -> status=insufficient_data, score=None
- varsa -> 100'den başlayıp severity'ye göre puan düşülür, reasoning'de
  hangi finding'lerin puanı düşürdüğü açıkça listelenir.
"""

from sqlalchemy.orm import Session

from packages.db.models import Business, BusinessMetric, Finding, OpportunityScore
from services.rule_engine.signal_rules import ALL_DIMENSIONS, CATEGORY_TO_DIMENSION, SEVERITY_SCORE_PENALTY


def _has_any_metric_for_dimension(db: Session, business_id: int, dimension: str) -> bool:
    # "yeterli veri yok" ile "veri var ama sorun yok" ayrımı için: ilgili kaynak veri var mı?
    if dimension == "web":
        return db.query(BusinessMetric).filter_by(business_id=business_id, metric_key="website_present").count() > 0
    if dimension == "google_visibility":
        return db.query(BusinessMetric).filter_by(business_id=business_id, metric_key="google_review_count").count() > 0
    return False  # seo/social/ads/design/print: sadece finding varsa veri var sayılır (aşağıda findings kontrol edilir)


def compute_opportunity_scores(
    db: Session, business: Business, analysis_job_id: int | None, findings: list[Finding]
) -> list[OpportunityScore]:
    findings_by_dimension: dict[str, list[Finding]] = {dim: [] for dim in ALL_DIMENSIONS}
    for finding in findings:
        dimension = CATEGORY_TO_DIMENSION.get(finding.category)
        if dimension:
            findings_by_dimension[dimension].append(finding)

    scores: list[OpportunityScore] = []
    for dimension in ALL_DIMENSIONS:
        dim_findings = findings_by_dimension[dimension]
        has_data = bool(dim_findings) or _has_any_metric_for_dimension(db, business.id, dimension)

        if not has_data:
            score = OpportunityScore(
                business_id=business.id,
                analysis_job_id=analysis_job_id,
                dimension=dimension,
                score=None,
                status="insufficient_data",
                reasoning="Bu boyut için yeterli veri toplanamadı (henüz bir kaynaktan ölçüm/kanıt yok).",
                based_on_finding_ids=[],
            )
        else:
            penalty = sum(SEVERITY_SCORE_PENALTY.get(f.severity, 0) for f in dim_findings)
            value = max(0, min(100, 100 - penalty))
            if dim_findings:
                reasons = "\n".join(f"- {f.finding}" for f in dim_findings)
                reasoning = f"{value}/100.\nNedenler:\n{reasons}"
            else:
                reasoning = f"{value}/100. Bu boyutta veri toplandı ve herhangi bir eksiklik tespit edilmedi."
            score = OpportunityScore(
                business_id=business.id,
                analysis_job_id=analysis_job_id,
                dimension=dimension,
                score=value,
                status="scored",
                reasoning=reasoning,
                based_on_finding_ids=[f.id for f in dim_findings],
            )
        db.add(score)
        scores.append(score)

    db.flush()
    return scores


def compute_overall_score(scores: list[OpportunityScore], findings: list[Finding] | None = None) -> tuple[int | None, str | None]:
    scored = [s for s in scores if s.status == "scored" and s.score is not None]
    if not scored:
        return None, None
    # Fırsat = eksiklik; düşük dimension skoru = yüksek satış fırsatı. Genel skor,
    # dimension skorlarının tersinin (100-score) ortalamasıdır.
    overall_opportunity = round(sum(100 - s.score for s in scored) / len(scored))
    coverage_ratio = len(scored) / len(ALL_DIMENSIONS)
    has_high_severity = any(f.severity == "high" for f in (findings or []))

    if overall_opportunity >= 55:
        priority = "Yüksek"
    elif overall_opportunity >= 30 or has_high_severity:
        priority = "Orta"
    else:
        priority = "Düşük"

    # Veri kapsamı dar ise "Yüksek" iddiasını sınırla — TEK İSTİSNA: somut, yüksek
    # önem dereceli bir bulgu (ör. web sitesi hiç yok) tek başına net bir satış
    # fırsatıdır, kapsam dar olsa bile bu iddiayı "Orta"ya düşürmeyi gerektirmez.
    if coverage_ratio < 0.4 and priority == "Yüksek" and not has_high_severity:
        priority = "Orta"

    return overall_opportunity, priority
