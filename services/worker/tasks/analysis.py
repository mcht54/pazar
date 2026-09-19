"""Derin analiz hattı: Google profili + web sitesi → kontroller → bulgular → hizmet eşleştirme → satış değerlendirmesi.

Akış:
1. google_profile : Keşif sırasında toplanan kaynak verisi (Google/OSM) — ek istek yapılmaz.
2. website        : İşletmenin web sitesi GERÇEKTEN açılıp ölçülür (varsa).
3. checks         : Deterministik kontroller (durum: sorun yok / sorun / doğrulanamadı).
4. findings       : Sorun bulunan her kontrol, kanıta (business_metrics kaydına) bağlı bir bulguya dönüşür.
5. recommendations: Bulguların bağlı olduğu hizmetler öncelik sırasıyla kaydedilir.
6. assessment     : Satış seviyesi + gerekçe + ilk/ikinci hizmet + görüşme notu.
7. competitor     : Aynı bölge/sektörden temel karşılaştırma (ek API çağrısı yok).
8. ai_interpretation: opsiyonel; anahtar yoksa atlanır.
"""

import dataclasses
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.base import SessionLocal
from packages.db.models import (
    AnalysisJob,
    Business,
    BusinessMetric,
    Finding,
    Region,
    SalesAssessment,
    Sector,
    ServiceCatalog,
    ServiceRecommendation,
)
from services.ai_orchestration.pipelines.interpret import run_ai_interpretation
from services.integrations.website_crawler.base import WebsiteSignals
from services.integrations.website_crawler.factory import get_website_analyzer
from services.rule_engine.checks import AnalysisContext, Check, build_gbp_checks, build_social_checks, build_website_checks
from services.rule_engine.competitor import build_competitor_snapshots
from services.rule_engine.opportunities import build_opportunities
from services.rule_engine.priority import compute_priority, why_prospect
from services.rule_engine.service_matrix import build_service_matrix
from services.rule_engine.sales import SEVERITY_LABEL_TR, Assessment, assess, maps_search_url
from services.rule_engine.scoring import compute_score
from services.research.service import get_or_run_research, latest_research
from services.rule_engine.sector_profiles import get_sector_profile
from services.rule_engine.service_lookup import resolve_service_ids
from services.worker.celery_app import celery_app

SOURCE_LABELS = {
    "google_maps": "Google Haritalar",
    "google_places": "Google Places API",
    "osm_overpass": "Eski keşif kaydı (OpenStreetMap)",
    "mock_demo": "DEMO veri (gerçek değil)",
}


def build_context(db: Session, business: Business, research: dict | None = None) -> AnalysisContext:
    sector = db.get(Sector, business.sector_id)
    region = db.get(Region, business.region_id)
    place_names = [region.name]
    if region.parent_region_id:
        parent = db.get(Region, region.parent_region_id)
        if parent is not None:
            place_names.append(parent.name)

    peers = (
        db.query(Business.google_review_count)
        .filter(
            Business.region_id == business.region_id,
            Business.sector_id == business.sector_id,
            Business.id != business.id,
            Business.google_review_count.isnot(None),
        )
        .all()
    )
    return AnalysisContext(
        business_name=business.name,
        peer_web=_peer_web_features(db, business),
        sector_name=sector.name,
        profile=get_sector_profile(sector.name, sector.group_name),
        sector_group=sector.group_name,
        sector_phrases=list(sector.keyword_variants or []),
        place_names=place_names,
        source=business.discovery_source,
        peer_review_counts=[row[0] for row in peers],
        research=research,
    )


def _peer_web_features(db: Session, business: Business) -> dict:
    """Aynı bölge+sektördeki diğer işletmelerin SON ölçülmüş web sitesi sinyallerinden özellik yaygınlığı (gerçek kayıtlar; uydurma yok)."""
    latest = (
        select(func.max(BusinessMetric.id))
        .join(Business, Business.id == BusinessMetric.business_id)
        .where(BusinessMetric.metric_key == "website.signals", BusinessMetric.status == "known", Business.id != business.id,
               Business.region_id == business.region_id, Business.sector_id == business.sector_id)
        .group_by(BusinessMetric.business_id)
    )
    rows = db.query(BusinessMetric.value).filter(BusinessMetric.id.in_(latest)).all()
    counts: dict[str, list[int]] = {}
    for (value,) in rows:
        v = value or {}
        flags = {
            "has_services_page": v.get("has_services_page"), "has_blog": v.get("has_blog"), "whatsapp_link_present": v.get("whatsapp_link_present"),
            "form_present": v.get("form_present"), "has_appointment_link": v.get("has_appointment_link"), "has_references_page": v.get("has_references_page"),
            "schema": bool(v.get("schema_types")) if "schema_types" in v else None,
        }
        for key, flag in flags.items():
            if flag is None:
                continue
            entry = counts.setdefault(key, [0, 0])
            entry[1] += 1
            entry[0] += 1 if flag else 0
    return {k: (a, b) for k, (a, b) in counts.items()}


def _signals_summary(signals: WebsiteSignals) -> dict:
    data = dataclasses.asdict(signals)
    data.pop("text_excerpt", None)  # uzun metin; izlenebilirlik için gerekmiyor
    return data


def _persist_metrics(db: Session, business: Business, job: AnalysisJob, checks: list[Check], signals: WebsiteSignals | None) -> dict[str, BusinessMetric]:
    """Her kontrol için bir ölçüm kaydı (kanıt zinciri): bulgular bu kayıtlara bağlanır."""
    by_key: dict[str, BusinessMetric] = {}
    for check in checks:
        metric = BusinessMetric(
            business_id=business.id,
            analysis_job_id=job.id,
            metric_key=f"{check.area}.{check.key}",
            value={"label": check.label, "value": check.value, "status": check.status, "detail": check.detail},
            status="not_available" if check.status == "unknown" else "known",
            source=check.source,
        )
        db.add(metric)
        by_key[f"{check.area}.{check.key}"] = metric
    if signals is not None:
        db.add(
            BusinessMetric(
                business_id=business.id, analysis_job_id=job.id, metric_key="website.signals",
                value=_signals_summary(signals), status="known" if signals.success else "not_available", source="website_crawl",
            )
        )
    db.flush()
    return by_key


def _persist_findings(db: Session, business: Business, job: AnalysisJob, checks: list[Check], metrics: dict[str, BusinessMetric]) -> list[Finding]:
    findings: list[Finding] = []
    for check in checks:
        if check.status != "problem":
            continue
        metric = metrics[f"{check.area}.{check.key}"]
        assert metric.id, f"'{check.key}' bulgusu kanıtsız oluşturulamaz (ölçüm kaydı yok)."
        finding = Finding(
            business_id=business.id,
            analysis_job_id=job.id,
            category=check.category,
            finding=check.value[:500],
            severity=check.severity,
            evidence=check.detail or check.value,
            source=check.source,
            confidence=check.confidence,
            detected_at=datetime.now(timezone.utc),
            based_on_metric_ids=[metric.id],
            business_impact=check.why or None,
            mchttasarim_opportunity=("Satılabilecek hizmet: " + ", ".join(check.services)) if check.services else None,
            recommended_service_ids=resolve_service_ids(db, check.services),
            raw_data={"check_key": check.key, "area": check.area, "needs_verification": check.needs_verification},
        )
        db.add(finding)
        findings.append(finding)
    db.flush()
    return findings


def _persist_recommendations(db: Session, business: Business, job: AnalysisJob, assessment: Assessment) -> dict[str, int]:
    """Kanıta dayalı hizmet önerileri (öncelik sırasıyla). Döndürür: hizmet adı -> service_id."""
    ids = {s.service: resolve_service_ids(db, (s.service,))[0] for s in assessment.services}
    for rank, opportunity in enumerate(assessment.services, start=1):
        matched = "; ".join(
            f"[{SEVERITY_LABEL_TR.get(c.severity, '-')}] {c.value}"
            for c in sorted(opportunity.problems, key=lambda c: -{"high": 3, "medium": 2, "low": 1}.get(c.severity, 0))
        )
        db.add(
            ServiceRecommendation(
                business_id=business.id, analysis_job_id=job.id, service_id=ids[opportunity.service],
                matched_rule=matched, priority_rank=rank, ai_justification=None,
            )
        )
    db.flush()
    return ids


def _build_payload(
    ctx: AnalysisContext, business: Business, assessment: Assessment, website_checks: list[Check], gbp_checks: list[Check],
    signals: WebsiteSignals | None, social_checks: list[Check] | None = None, all_checks: list[Check] | None = None, partial: bool = False,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    website_info: dict = {"url": business.website, "analyzed": bool(signals and signals.success), "checked_at": now, "checks": [c.to_dict() for c in website_checks]}
    if not business.website:
        website_info["status_text"] = "Web sitesi bulunamadı."
    elif signals is None:
        website_info["status_text"] = "Web sitesi henüz analiz edilmedi."
    elif signals.success:
        website_info.update(
            status_text="Web sitesi açıldı ve analiz edildi.", final_url=signals.final_url, http_status=signals.http_status,
            response_ms=signals.response_ms, pagespeed=signals.pagespeed, pagespeed_note=signals.pagespeed_error if not signals.pagespeed else None,
            generator=signals.generator, title=signals.title, meta_description=signals.meta_description, h1=signals.h1_texts[:3],
            word_count=signals.word_count,
        )
    else:
        website_info.update(status_text=f"Web sitesi analiz edilemedi — {signals.error_reason}", error=signals.error_reason, outcome=signals.outcome)

    google = ctx.is_google_data
    research = ctx.research or {}
    if ctx.google_profile is not None and ctx.google_profile.get("source") == "google_api":
        gbp_source_label, gbp_status_text = (
            "Google Places API",
            "Google Haritalar okunamadığı/eşleşmediği için Google Places API kaydı kullanıldı: " + ", ".join((ctx.google_profile.get("match") or {}).get("signals", [])) + ".",
        )
    elif ctx.google_profile is not None:
        gbp_source_label, gbp_status_text = (
            "Google Haritalar (herkese açık İşletme Profili)",
            "Google İşletme Profili Google Haritalar'dan okundu ve işletmeyle eşleştirildi: " + ", ".join((ctx.google_profile.get("match") or {}).get("signals", [])) + ".",
        )
    elif google:
        gbp_source_label, gbp_status_text = SOURCE_LABELS.get(business.discovery_source, business.discovery_source), "Google İşletme Profili verisi Google Places API'den alındı."
    else:
        status = ctx.source_status("google_maps")
        gbp_source_label = "Google Haritalar"
        gbp_status_text = (
            f"Google İşletme Profili: {'ERİŞİLEMEDİ' if status['status'] == 'erisilemedi' else 'EŞLEŞME YOK'} — {status['detail']}" if status
            else "Google İşletme Profili sorgulanmadı; Google'a ait alanlar Doğrulanamadı olarak gösterilir."
        )
    gbp_info = {
        "source": business.discovery_source,
        "source_label": gbp_source_label,
        "available": google,
        "checked_at": business.source_checked_at.isoformat() if business.source_checked_at else None,
        "maps_url": business.maps_url,
        "maps_search_url": maps_search_url(business.name, business.address, ctx.place),
        "checks": [c.to_dict() for c in gbp_checks],
        "status_text": gbp_status_text,
    }
    every_check = all_checks or (website_checks + gbp_checks + (social_checks or []))
    score = compute_score(every_check, assessment.possible_services)
    # HİZMET MATRİSİ: Mchttasarım'ın her hizmeti tek tek (🟢/🟡/⚪/🔴), kanıt + gerekçe + ne yapılır + müşteriye nasıl anlatılır
    matrix = build_service_matrix(ctx, every_check, business=business, signals=signals, has_website=bool(business.website))
    measured = [c for c in every_check if c.area in ("website", "gbp")]
    completeness = (sum(1 for c in measured if c.status != "unknown") / len(measured)) if measured else 0.5
    priority = compute_priority(score=score["score"], matrix=matrix, completeness=completeness * (0.85 if partial else 1.0), has_phone=bool(business.phone))
    return {
        "service_matrix": matrix,
        "priority": priority,
        "why_prospect": why_prospect(matrix),
        "gaps": [c.to_dict() for c in assessment.gaps[:10]],
        "strengths": [{"label": c.label, "value": c.value} for c in assessment.strengths if c.key not in ("presence", "access")][:12],
        "services": [
            {
                "service": s.service,
                "is_primary": i == 0,
                "reasons": [c.value for c in sorted(s.problems, key=lambda c: -{"high": 3, "medium": 2, "low": 1}.get(c.severity, 0))][:4],
            }
            for i, s in enumerate(assessment.services)
        ],
        "possible_services": assessment.possible_services,
        "verification_steps": assessment.verification_steps,
        "website": website_info,
        "gbp": gbp_info,
        "opportunities": build_opportunities(assessment),
        "score": score,
        "social": [c.to_dict() for c in (social_checks or [])],
        "research": {
            "checked_at": research.get("checked_at"),
            "sources": research.get("sources", []),
            "verdicts": research.get("verdicts", {}),
            "social": research.get("social", []),
            "notes": research.get("notes", []),
            "candidates": research.get("candidates", []),
        },
    }


def _fail_business(db: Session, business: Business, job: AnalysisJob, stages: dict[str, str]) -> None:
    db.rollback()
    business = db.get(Business, business.id)
    job = db.get(AnalysisJob, job.id)
    business.status = "analysis_failed"
    job.status = "failed"
    job.stages_status = stages
    job.completed_at = datetime.now(timezone.utc)
    db.commit()


def _record_user_analysis(db: Session, job: AnalysisJob, business: Business, payload: dict) -> None:
    """Kullanıcı bazlı analiz özeti: yalnızca BAŞARIYLA tamamlanan (completed), kullanıcısı bilinen ve bakım olmayan analizler.
    Aynı kullanıcı aynı işletmeyi yeniden analiz ederse mevcut satır güncellenir (runs+1); başka kullanıcının kaydına dokunulmaz."""
    if job.status != "completed" or job.user_id is None or job.trigger == "maintenance":
        return
    from packages.db.models import UserAnalysis

    summary = {"status": "completed", "score": (payload.get("score") or {}).get("score"), "level": (payload.get("assessment") or {}).get("level")}
    row = db.query(UserAnalysis).filter_by(user_id=job.user_id, business_id=business.id, analysis_type="deep").one_or_none()
    if row is None:
        db.add(UserAnalysis(user_id=job.user_id, business_id=business.id, analysis_type="deep", analysis_job_id=job.id, analysis_result=summary, runs=1))
    else:
        row.analysis_job_id, row.analysis_result, row.runs, row.updated_at = job.id, summary, (row.runs or 0) + 1, job.completed_at


def run_analysis_job(db: Session, analysis_job_id: int, force_research: bool = False, allow_new_research: bool = True) -> AnalysisJob:
    job = db.get(AnalysisJob, analysis_job_id)
    if job is None:
        raise ValueError(f"AnalysisJob {analysis_job_id} bulunamadı")

    business = db.get(Business, job.business_id)
    stages: dict[str, str] = {}

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()

    try:
        # 1) Çok kaynaklı araştırma: Google Haritalar + Bing Haritalar + resmi web sitesi + sosyal medya + çapraz doğrulama.
        #    Bir kaynak başarısız olsa bile analiz diğer kaynaklarla sürer (kaynak durumu kaydedilir).
        research_payload: dict | None = None
        no_cached_research = not allow_new_research and latest_research(db, business.id) is None
        if not settings.research_enabled or business.discovery_source == "mock_demo" or no_cached_research:
            stages["research"] = "skipped"  # kapalı ya da DEMO işletme: gerçek olmayan bir işletme için dış kaynaklara istek atılmaz
            stages["google_profile"] = "skipped"
        else:
            try:
                record, ran = get_or_run_research(db, business, force=force_research)
                research_payload = record.payload
                stages["research"] = "success" if ran else "cached"
                google_status = next((x for x in research_payload.get("sources", []) if x["key"] == "google_maps"), None)
                stages["google_profile"] = (
                    "success" if research_payload.get("google")
                    else ("failed" if google_status and google_status["status"] == "erisilemedi" else "skipped")
                )
            except Exception:
                stages["research"] = "failed"
                stages["google_profile"] = "failed"

        ctx = build_context(db, business, research_payload)

        # 2) Web sitesi: gerçekten açılıp ölçülür.
        signals: WebsiteSignals | None = None
        if business.website:
            try:
                analyzer = get_website_analyzer(business_is_demo=business.discovery_source == "mock_demo")
                signals = analyzer.analyze(business.website)
            except Exception as exc:  # beklenmeyen tarayıcı hatası — analizi komple düşürme
                signals = WebsiteSignals(success=False, outcome="unreachable", failure_kind="connect", error_reason=f"Beklenmeyen hata: {type(exc).__name__}")
            stages["website"] = "success" if signals.success else "failed"
        else:
            stages["website"] = "skipped"

        # 3) Kontroller
        website_checks = build_website_checks(ctx, business.website, signals)
        gbp_checks = build_gbp_checks(ctx, business)
        social_checks = build_social_checks(ctx)
        all_checks = website_checks + gbp_checks + social_checks

        # 4) Kanıt zinciri: ölçümler -> bulgular
        metrics = _persist_metrics(db, business, job, all_checks, signals)
        _persist_findings(db, business, job, all_checks, metrics)
        stages["evidence_extraction"] = "success"

        # 5-6) Satış değerlendirmesi ve hizmet önerileri
        assessment = assess(
            ctx, all_checks, has_website=bool(business.website),
            contactable_phone=bool(business.phone), contactable_email=bool(business.email), conflicts=ctx.conflicts,
        )
        ids = _persist_recommendations(db, business, job, assessment)
        stages["rule_engine"] = "success"

        partial_run = "failed" in (stages["website"], stages["research"])
        payload = _build_payload(ctx, business, assessment, website_checks, gbp_checks, signals, social_checks, all_checks, partial=partial_run)
        is_actionable = bool(assessment.top_opportunity)  # sadece Yüksek/Orta seviyede ilk/ikinci hizmet önerilir
        # Önerilen ilk/ikinci hizmet: hizmet matrisindeki en güçlü 🟢 (yoksa kanıtlı 🟡) hizmetler; matris boşsa eski değerlendirme
        matrix_top = [i["service"] for i in payload["service_matrix"]["items"] if i["level"] == "satis"][:2]
        if len(matrix_top) < 2:
            matrix_top += [i["service"] for i in payload["service_matrix"]["items"] if i["level"] == "olasi" and not i["sector_only"] and i["service"] not in matrix_top][: 2 - len(matrix_top)]
        matrix_ids = dict(zip(matrix_top, resolve_service_ids(db, tuple(matrix_top)))) if matrix_top else {}
        db.add(
            SalesAssessment(
                business_id=business.id,
                analysis_job_id=job.id,
                level=assessment.level,
                level_reason=assessment.level_reason,
                rank_score=assessment.rank_score,
                needs_verification=assessment.needs_verification,
                primary_service_id=(matrix_ids[matrix_top[0]] if matrix_top else (ids[assessment.services[0].service] if is_actionable else None)),
                secondary_service_id=(matrix_ids[matrix_top[1]] if len(matrix_top) > 1 else (ids[assessment.services[1].service] if not matrix_top and is_actionable and len(assessment.services) > 1 else None)),
                top_opportunity=assessment.top_opportunity,
                why_call=assessment.why_call,
                talking_point=assessment.talking_point,
                sales_note=assessment.sales_note,
                payload=payload,
            )
        )
        business.opportunity_score_total = payload["score"]["score"]  # 0-100 satış fırsatı puanı (açıklamasıyla payload["score"] içinde)
        business.sales_priority = assessment.level
        stages["scoring"] = "success"

        # 7) Rakip karşılaştırması (aynı bölge/sektör, ek API çağrısı yok)
        competitors = build_competitor_snapshots(db, business, job.id)
        stages["competitor"] = "success" if competitors else "skipped"

        # 8) AI yorumlama (opsiyonel — ANTHROPIC_API_KEY yoksa atlanır)
        try:
            stages["ai_interpretation"] = run_ai_interpretation(db, business.id, job.id)
        except NotImplementedError:
            stages["ai_interpretation"] = "skipped"

        # Analizin GERÇEK tamamlanma anı: firmanın "son analiz tarihi" ile analiz geçmişindeki kayıt (analysis_jobs.completed_at) aynıdır.
        # Analiz firmayı CRM'e eklemez ve mevcut CRM kaydına/geçmişine dokunmaz.
        completed_at = datetime.now(timezone.utc)
        business.status = "analyzed"
        business.last_analysis_at = completed_at
        job.status = "partial" if "failed" in (stages["website"], stages["research"]) else "completed"
        job.stages_status = stages
        job.completed_at = completed_at
        _record_user_analysis(db, job, business, payload)
        db.commit()
        return job
    except Exception:
        stages.setdefault("evidence_extraction", "failed")
        _fail_business(db, business, job, stages)
        raise


@celery_app.task(name="worker.run_analysis_job")
def run_analysis_job_task(analysis_job_id: int, force_research: bool = False) -> str:
    """force_research=True: kullanıcı 'Analizi Yenile'ye bastı — önbellekteki (7 gün) araştırma yerine kaynaklar yeniden sorgulanır."""
    db = SessionLocal()
    try:
        job = run_analysis_job(db, analysis_job_id, force_research=force_research)
        return job.status
    finally:
        db.close()
