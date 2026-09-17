"""Deterministik Evidence Extraction — AI KULLANILMAZ.

business_metrics kayıtlarını okuyup Finding üretir. Her Finding en az bir
business_metrics kaydına (based_on_metric_ids) dayanmak zorundadır; kanıtsız
Finding oluşturulamaz (kod seviyesinde AssertionError ile engellenir).
"""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from packages.db.models import Business, BusinessMetric, Finding
from services.rule_engine.service_lookup import resolve_service_ids
from services.rule_engine.signal_rules import (
    LOW_PHOTO_COUNT_THRESHOLD,
    LOW_REVIEW_COUNT_THRESHOLD,
    SIGNAL_RULES,
)


def latest_metrics_by_key(db: Session, business_id: int) -> dict[str, BusinessMetric]:
    subq = (
        db.query(BusinessMetric.metric_key, func.max(BusinessMetric.id).label("max_id"))
        .filter(BusinessMetric.business_id == business_id)
        .group_by(BusinessMetric.metric_key)
        .subquery()
    )
    rows = (
        db.query(BusinessMetric)
        .join(subq, BusinessMetric.id == subq.c.max_id)
        .all()
    )
    return {row.metric_key: row for row in rows}


def _metric_value(metric: BusinessMetric | None):
    if metric is None or metric.value is None:
        return None
    return metric.value.get("value")


def _add_finding(
    db: Session,
    business: Business,
    analysis_job_id: int | None,
    signal_key: str,
    metric_ids: list[int],
    evidence: str,
    extra_service_names: tuple[str, ...] = (),
) -> Finding:
    rule = SIGNAL_RULES[signal_key]
    assert metric_ids, f"'{signal_key}' finding'i kanıtsız oluşturulamaz (based_on_metric_ids boş)."

    service_names = rule.service_names + extra_service_names
    finding = Finding(
        business_id=business.id,
        analysis_job_id=analysis_job_id,
        category=rule.category,
        finding=rule.finding,
        severity=rule.severity,
        evidence=evidence,
        source=rule.source,
        confidence=rule.confidence,
        detected_at=datetime.now(timezone.utc),
        based_on_metric_ids=metric_ids,
        business_impact=rule.business_impact,
        mchttasarim_opportunity=rule.mchttasarim_opportunity,
        recommended_service_ids=resolve_service_ids(db, service_names),
    )
    db.add(finding)
    return finding


def extract_findings(db: Session, business: Business, analysis_job_id: int | None) -> list[Finding]:
    metrics = latest_metrics_by_key(db, business.id)
    findings: list[Finding] = []

    website_present = metrics.get("website_present")
    if website_present is not None and _metric_value(website_present) is False:
        findings.append(
            _add_finding(
                db, business, analysis_job_id, "website_missing",
                [website_present.id],
                SIGNAL_RULES["website_missing"].evidence_template.format(google_place_id=business.google_place_id),
            )
        )

    website_reachable = metrics.get("website_reachable")
    if website_reachable is not None and _metric_value(website_reachable) is False:
        error_reason = (website_reachable.value or {}).get("error_reason", "bilinmiyor")
        findings.append(
            _add_finding(
                db, business, analysis_job_id, "website_unreachable",
                [website_reachable.id],
                SIGNAL_RULES["website_unreachable"].evidence_template.format(
                    website=business.website, error_reason=error_reason
                ),
            )
        )

    def _crawl_signal_finding(metric_key: str, signal_key: str):
        metric = metrics.get(metric_key)
        if metric is not None and _metric_value(metric) is False:
            findings.append(
                _add_finding(
                    db, business, analysis_job_id, signal_key,
                    [metric.id],
                    SIGNAL_RULES[signal_key].evidence_template.format(website=business.website),
                )
            )

    _crawl_signal_finding("https_enabled", "https_missing")
    _crawl_signal_finding("title_present", "title_missing")
    _crawl_signal_finding("meta_description_present", "meta_description_missing")
    _crawl_signal_finding("h1_present", "h1_missing")
    _crawl_signal_finding("schema_markup_present", "schema_missing")

    whatsapp = metrics.get("whatsapp_link_present")
    phone_link = metrics.get("phone_link_present")
    reservation = metrics.get("reservation_link_present")
    cta_metrics = [m for m in (whatsapp, phone_link, reservation) if m is not None]
    if cta_metrics and all(_metric_value(m) is False for m in cta_metrics):
        findings.append(
            _add_finding(
                db, business, analysis_job_id, "no_cta_link",
                [m.id for m in cta_metrics],
                SIGNAL_RULES["no_cta_link"].evidence_template.format(website=business.website),
            )
        )

    instagram = metrics.get("instagram_link_present")
    facebook = metrics.get("facebook_link_present")
    social_metrics = [m for m in (instagram, facebook) if m is not None]
    if social_metrics and all(_metric_value(m) is False for m in social_metrics):
        findings.append(
            _add_finding(
                db, business, analysis_job_id, "social_not_linked",
                [m.id for m in social_metrics],
                SIGNAL_RULES["social_not_linked"].evidence_template.format(website=business.website),
            )
        )

    review_count_metric = metrics.get("google_review_count")
    review_count = _metric_value(review_count_metric)
    if review_count_metric is not None and review_count is not None and review_count < LOW_REVIEW_COUNT_THRESHOLD:
        findings.append(
            _add_finding(
                db, business, analysis_job_id, "low_review_count",
                [review_count_metric.id],
                SIGNAL_RULES["low_review_count"].evidence_template.format(
                    review_count=review_count, threshold=LOW_REVIEW_COUNT_THRESHOLD
                ),
            )
        )

    photo_count_metric = metrics.get("photo_count")
    photo_count = _metric_value(photo_count_metric)
    if photo_count_metric is not None and photo_count is not None and photo_count < LOW_PHOTO_COUNT_THRESHOLD:
        findings.append(
            _add_finding(
                db, business, analysis_job_id, "low_photo_count",
                [photo_count_metric.id],
                SIGNAL_RULES["low_photo_count"].evidence_template.format(
                    photo_count=photo_count, threshold=LOW_PHOTO_COUNT_THRESHOLD
                ),
            )
        )

    db.flush()
    return findings
