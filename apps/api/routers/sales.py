"""Satış operasyonu: 'Bugün Kimi Aramalıyım?', firma satış planı (Ne satabilirim?), huni, gelir ve personel raporları."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api.deps import require
from apps.api.routers.businesses import _build_business_out, _latest_assessments, _load_extras, _presentation_maps
from packages.crm import CLOSED_STAGES
from packages.db.base import get_db
from packages.db.models import Business, CrmActivity, User
from services import crm_service
from services.reporting.analysis_stats import PERIODS, TZ
from services.rule_engine.prospect import assess_business
from services.sales import pricing, reports
from services.sales.call_priority import score_call
from services.sales.providers import build_provider_signals, latest_site_signals
from services.sales.scripts import build_scripts

router = APIRouter(prefix="/api/sales", tags=["satış"])

SCAN_LIMIT = 600
SOURCE_LABELS = {"gbp": "Google", "website": "Website", "social": "Social", "derived": "Çapraz kontrol"}


def _period(period: str) -> str:
    if period not in PERIODS:
        raise HTTPException(status_code=422, detail=f"Geçersiz dönem. Geçerli: {', '.join(PERIODS)}")
    return period


def _mobile(phone: str | None) -> bool:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-10:].startswith("5") if len(digits) >= 10 else False


SOURCE_LABELS_CALL = {
    "takip_gecikmis": "🚨 Gecikmiş takip", "takip_bugun": "📅 Bugün takip günü", "temas_sonuclanmamis": "📞 Temas edildi, sonuçlanmadı",
    "yeni_lead": "🆕 Yeni lead", "yeni_analiz": "🔍 Analiz edilmiş, CRM'de değil",
}


def _sources(b: Business) -> list[dict]:
    """Firmanın 'Bugün kimi arayalım?' listesine hangi kaynaktan girdiği (birden çok olabilir). Yalnızca gerçek kayıtlara dayanır."""
    keys = []
    state = crm_service.follow_up_state(b)
    if state == "overdue":
        keys.append("takip_gecikmis")
    elif state == "today":
        keys.append("takip_bugun")
    if b.crm_added_at is None:
        keys.append("yeni_analiz")
    elif b.crm_stage in ("Arandı", "Görüşüldü", "Teklif Gönderildi") and state is None:
        keys.append("temas_sonuclanmamis")
    elif b.crm_stage in ("Yeni", "Aranacak") and state is None:
        keys.append("yeni_lead")
    return [{"key": k, "label": SOURCE_LABELS_CALL[k]} for k in keys]


# ------------------------------------------------------------------ 🔥 Bugün Kimi Aramalıyım?
@router.get("/call-today")
def call_today(limit: int = 15, scope: str = "mine", min_score: int = 15, user: User = Depends(require("dashboard")), db: Session = Depends(get_db)):
    """Satış ÖNCELİK puanına göre bugün aranacak firmalar + 'Neden bugün aranmalı?' gerekçesi.

    Adaylar: (1) CRM'deki açık kayıtlar (bana ait ya da sahipsiz; `scope=all` tümü), (2) analizi tamamlanmış, henüz CRM'e alınmamış firmalar.
    Elenenler ve nedenleri `excluded` altında sayılarıyla döner (kapanmış, takip tarihi ileri, bugün görüşülmüş, kamu/rakip/kendisi).
    """
    if scope not in ("mine", "all"):
        raise HTTPException(status_code=422, detail="scope 'mine' ya da 'all' olmalı")
    limit = max(1, min(limit, 50))
    now = datetime.now(timezone.utc)

    crm_rows = db.query(Business).filter(Business.crm_added_at.isnot(None), ~Business.crm_stage.in_(CLOSED_STAGES)).all()
    if scope == "mine":
        crm_rows = [b for b in crm_rows if b.crm_owner_id in (user.id, None)]
    fresh = (
        db.query(Business)
        .filter(Business.status == "analyzed", Business.crm_added_at.is_(None), Business.opportunity_score_total >= min_score)
        .order_by(Business.opportunity_score_total.desc(), Business.id.desc()).limit(SCAN_LIMIT).all()
    )
    candidates = {b.id: b for b in crm_rows + fresh}
    ids = list(candidates)
    assessments = _latest_assessments(db, ids)
    sector_names, region_labels, service_names = _presentation_maps(db)
    attempts = crm_service.contact_attempts(db, ids)

    scored, excluded = [], {}
    for b in candidates.values():
        a = assessments.get(b.id)
        in_crm = b.crm_added_at is not None
        if not in_crm and (a is None or a.level == "Belirsiz" or not assess_business(b, sector_names.get(b.sector_id)).eligible):
            excluded["Uygun müşteri adayı değil (kamu/rakip/kendisi) ya da analiz belirsiz"] = excluded.get("Uygun müşteri adayı değil (kamu/rakip/kendisi) ya da analiz belirsiz", 0) + 1
            continue
        payload = (a.payload or {}) if a else {}
        result = score_call(
            priority_value=(payload.get("priority") or {}).get("value") if a else None, matrix=payload.get("service_matrix"),
            has_phone=bool(b.phone), has_email=bool(b.email), mobile_phone=_mobile(b.phone), review_count=b.google_review_count,
            provider_wins=0, crm_stage=b.crm_stage, in_crm=in_crm, follow_state=crm_service.follow_up_state(b, now), follow_at=b.next_follow_up_at,
            last_contact_at=b.last_contact_at, call_attempts=attempts.get(b.id, 0), now=now,
        )
        if result["excluded"]:
            reason = result["excluded"].split(" (")[0]
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        scored.append((result, b))
    # Takibi gelen/geciken firmalar (personelin kendi planı) her zaman önde: önce gecikmiş, sonra bugünkü; sonra kalanlar puana göre
    tier = {"overdue": 0, "today": 1}
    scored.sort(key=lambda x: (tier.get(crm_service.follow_up_state(x[1], now), 2), -x[0]["score"], 0 if x[1].phone else 1, x[1].id))
    top = scored[:limit]
    extras = _load_extras(db, [b for _, b in top], user)
    items = []
    for result, b in top:
        out = _build_business_out(b, sector_names=sector_names, region_labels=region_labels, service_names=service_names, assessment=assessments.get(b.id), extras=extras)
        items.append({"business": out.model_dump(mode="json"), "call": {**{k: result[k] for k in ("score", "reasons", "components", "weights", "next_action")}, "sources": _sources(b)}})
    return {"items": items, "total_candidates": len(candidates), "eligible": len(scored), "excluded": excluded, "scope": scope, "updated_at": now.astimezone(TZ).isoformat()}


# ------------------------------------------------------------------ Ne satabilirim? (firma satış planı)
@router.get("/plan/{business_id}")
def sales_plan(business_id: int, user: User = Depends(require("view_business")), db: Session = Depends(get_db)):
    """Firma için satış planı: hizmet bazlı ihtiyaç/seviye/kanıt+kaynak/öncelik/yaklaşım, tahmini değer ve paket, mevcut sağlayıcı sinyalleri,
    kaynaklar arası çelişkiler ve kişiselleştirilmiş satış metinleri. Kanıtsız hiçbir şey olgu gibi yazılmaz."""
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="İşletme bulunamadı")
    assessment = _latest_assessments(db, [business_id]).get(business_id)
    sector_names, region_labels, _ = _presentation_maps(db)
    if assessment is None:
        return {"business_id": business_id, "analyzed": False, "message": "Bu firma henüz analiz edilmedi; satış planı için önce analiz gerekir.", "opportunities": []}
    payload = assessment.payload or {}
    matrix = payload.get("service_matrix") or {"items": []}
    prices = pricing.price_map(db)

    actionable = [i for i in matrix["items"] if i["level"] in ("satis", "olasi")]
    rank_of = {i["service"]: n + 1 for n, i in enumerate(actionable)}
    opportunities = []
    for item in matrix["items"]:
        evidence = [{**e, "source_label": SOURCE_LABELS.get(e.get("area"), "Doğrulanamadı"), "state": "dogrulandi" if e.get("verified") else "dogrulanmadi"} for e in item["evidence"]]
        opportunities.append({
            "service": item["service"], "level": item["level"], "level_label": item["level_label"], "need": item["problem"], "why": item["why"],
            "priority": rank_of.get(item["service"]), "approach": item["pitch"], "what": item["what"], "caveat": item["caveat"], "evidence": evidence,
            "sources": sorted({e["source_label"] for e in evidence}) or ["Doğrulanamadı"], "sector_only": item["sector_only"],
            "recurring": item["recurring"], "guide_id": item["guide_id"], "estimate": pricing.estimate(item["service"], prices) if item["level"] in ("satis", "olasi") else None,
            "evidence_note": None if evidence else "Kanıt yok — Doğrulanamadı (yalnızca sektöre dayalı olası ihtiyaç).",
        })
    package_services = [i["service"] for i in actionable if i["level"] == "satis" or not i["sector_only"]][:3]
    signals = latest_site_signals(db, business_id)
    verification = (payload.get("research") or {}).get("verdicts") or {}
    social_verified = sum(1 for s in (payload.get("social") or []) if s.get("status") == "ok")
    providers = build_provider_signals(signals, matrix, has_website=bool(business.website), social_verified=social_verified)
    flags = [
        {"field": v.get("label") or k, "note": v.get("note"), "sources": [{"label": s.get("label"), "value": s.get("value")} for s in v.get("sources", [])]}
        for k, v in verification.items() if v.get("status") == "celiskili"
    ]
    region = region_labels.get(business.region_id, "")
    scripts = build_scripts(business_name=business.name, sector_name=sector_names.get(business.sector_id), place=region.split(",")[0] if region else None,
                            matrix=matrix, staff_name=user.name, provider_wins=providers["win_opportunities"])
    return {
        "business_id": business_id, "analyzed": True, "opportunities": opportunities, "package": pricing.package_estimate(package_services, prices),
        "providers": providers, "cross_check_flags": flags, "scripts": scripts, "why_prospect": payload.get("why_prospect", []),
        "priority": payload.get("priority"), "site_signals_available": signals is not None,
    }


# ------------------------------------------------------------------ raporlar
@router.get("/funnel")
def funnel(period: str = "total", _: User = Depends(require("sales_reports")), db: Session = Depends(get_db)):
    return reports.funnel(db, _period(period))


@router.get("/revenue")
def revenue(by: str = "service", period: str = "total", _: User = Depends(require("sales_reports")), db: Session = Depends(get_db)):
    if by not in ("service", "sector"):
        raise HTTPException(status_code=422, detail="by: service | sector")
    return reports.revenue(db, by, _period(period))


@router.get("/suggestions")
def suggestions(_: User = Depends(require("sales_reports")), db: Session = Depends(get_db)):
    return reports.suggestions(db)


@router.get("/staff")
def staff(period: str = "today", _: User = Depends(require("staff_reports")), db: Session = Depends(get_db)):
    return reports.staff_performance(db, _period(period))


@router.get("/report")
def report(period: str = "today", _: User = Depends(require("staff_reports")), db: Session = Depends(get_db)):
    return reports.overview(db, _period(period))
