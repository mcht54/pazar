"""Rule Engine: Finding'lerden deterministik ServiceRecommendation üretir.

AI bu aşamaya karışmaz. Girdi: evidence_extraction'ın ürettiği Finding'ler.
Çıktı: her önerilen hizmet için, hangi Finding'lere dayandığını (matched_rule)
ve öncelik sırasını (priority_rank) gösteren ServiceRecommendation kayıtları.
"""

from sqlalchemy.orm import Session

from packages.db.models import Finding, ServiceRecommendation

SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1, "none": 0}


def build_service_recommendations(
    db: Session, business_id: int, analysis_job_id: int | None, findings: list[Finding]
) -> list[ServiceRecommendation]:
    by_service: dict[int, list[Finding]] = {}
    for finding in findings:
        for service_id in finding.recommended_service_ids:
            by_service.setdefault(service_id, []).append(finding)

    scored = [
        (service_id, sum(SEVERITY_WEIGHT.get(f.severity, 0) for f in contributing_findings), contributing_findings)
        for service_id, contributing_findings in by_service.items()
    ]
    scored.sort(key=lambda row: row[1], reverse=True)

    recommendations: list[ServiceRecommendation] = []
    for rank, (service_id, _weight, contributing_findings) in enumerate(scored, start=1):
        matched_rule = "; ".join(f"[{f.severity}] {f.finding}" for f in contributing_findings)
        recommendation = ServiceRecommendation(
            business_id=business_id,
            analysis_job_id=analysis_job_id,
            service_id=service_id,
            matched_rule=matched_rule,
            priority_rank=rank,
            ai_justification=None,  # Sprint 1: AI aşaması opsiyonel/atlanabilir — bkz. ai_orchestration
        )
        db.add(recommendation)
        recommendations.append(recommendation)

    db.flush()
    return recommendations
