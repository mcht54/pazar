"""Satış raporları: huni, hizmet/sektör bazlı gelir, personel performansı, dönemsel özet ve nesnel öneriler.

İLKELER
- Her sayı gerçek CRM/analiz kayıtlarından hesaplanır (crm_activities, businesses, analysis_jobs, sales_assessments). Kodda örnek/uydurma veri yoktur.
- Tutarlar personelin girdiği teklif/satış tutarlarıdır. Tutar girilmemiş satış SAYILIR ama tutar toplamına 0 katkı verir ve ayrıca "tutar girilmedi" olarak gösterilir.
- Hiçbir sektör/hizmet "en kârlı" diye önceden ilan edilmez; sıralama yalnızca veriden çıkar. Örneklem küçükse ("Yeterli veri bulunmuyor.") sonuç/öneri üretilmez.
- Dönemler Europe/Istanbul yarı-açık aralıklardır (services/reporting/analysis_stats.period_bounds).
"""

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from packages.crm import FUNNEL_RANK, FUNNEL_STEPS, OPEN_STAGES
from packages.db.models import ActivityLog, AnalysisJob, Business, CrmActivity, Sector, SalesAssessment, User
from services.crm_service import follow_up_state
from services.reporting.analysis_stats import PERIODS, TZ, analysis_report, analyzed_business_ids, period_bounds
from services.rule_engine.prospect import assess_business

# Durum GEÇİŞİ = CRM'e ekleme ya da aşaması gerçekten değişen durum/iletişim kaydı. Not, takip, satış-bilgisi güncellemesi ve aşamayı değiştirmeyen
# iletişim denemesi geçiş SAYILMAZ (bu kayıtlarda to_stage yalnızca mevcut aşamayı taşır).
TRANSITION = or_(CrmActivity.type == "added", and_(CrmActivity.type.in_(("status_change", "contact")), CrmActivity.from_stage != CrmActivity.to_stage))
MIN_SAMPLE = 5  # bu kadar teklif/kayıttan az olan gruplar için oran/öneri üretilmez
NO_DATA = "Yeterli veri bulunmuyor."
UNSPECIFIED = "Belirtilmedi"


def _in(column, start, end):
    conds = []
    if start is not None:
        conds.append(column >= start)
    if end is not None:
        conds.append(column < end)
    return conds


def _rate(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _latest_assessments(db: Session, ids: list[int]) -> dict[int, SalesAssessment]:
    if not ids:
        return {}
    latest = select(func.max(SalesAssessment.id)).where(SalesAssessment.business_id.in_(ids)).group_by(SalesAssessment.business_id)
    return {a.business_id: a for a in db.query(SalesAssessment).filter(SalesAssessment.id.in_(latest)).all()}


def _has_real_opportunity(assessment: SalesAssessment | None) -> bool:
    if assessment is None or assessment.level == "Belirsiz":
        return False
    items = ((assessment.payload or {}).get("service_matrix") or {}).get("items", [])
    return any(i["level"] == "satis" or (i["level"] == "olasi" and not i["sector_only"]) for i in items)


def _primary_service(assessment: SalesAssessment | None) -> str | None:
    items = ((assessment.payload or {}).get("service_matrix") or {}).get("items", []) if assessment else []
    return next((i["service"] for i in items if i.get("primary")), None)


def _green_services(assessment: SalesAssessment | None) -> list[str]:
    items = ((assessment.payload or {}).get("service_matrix") or {}).get("items", []) if assessment else []
    return [i["service"] for i in items if i["level"] == "satis"]


def _reached_ranks(db: Session, ids: list[int]) -> dict[int, int]:
    """Her firmanın geçmişte ULAŞTIĞI en ileri huni sırası (0 = hiç arama/görüşme yok). Geçmiş aktivite + güncel durum birlikte değerlendirilir."""
    ranks: dict[int, int] = defaultdict(int)
    if not ids:
        return ranks
    for bid, stage in db.query(CrmActivity.business_id, CrmActivity.to_stage).filter(CrmActivity.business_id.in_(ids), CrmActivity.to_stage.isnot(None)).distinct().all():
        ranks[bid] = max(ranks[bid], FUNNEL_RANK.get(stage, 0))
    for bid, stage in db.query(Business.id, Business.crm_stage).filter(Business.id.in_(ids), Business.crm_added_at.isnot(None)).all():
        ranks[bid] = max(ranks[bid], FUNNEL_RANK.get(stage, 0))
    return ranks


# ------------------------------------------------------------------ huni
def funnel(db: Session, period: str = "total", now: datetime | None = None) -> dict:
    """Satış hunisi (kohort): seçilen dönemde ANALİZİ TAMAMLANAN firmaların ilerleyişi.

    Analiz → Potansiyel (gerçek fırsatı olan ya da CRM'e alınan) → Arandı → Görüşme → Teklif (gönderildi) → Kazanıldı.
    Her adım bir öncekinin alt kümesidir (bir firma ulaştığı en ileri aşamaya göre sayılır), bu yüzden oranlar %100'ü aşmaz.
    """
    now = now or datetime.now(timezone.utc)
    ids, _ = analyzed_business_ids(db, period, now)
    businesses = {b.id: b for b in db.query(Business).filter(Business.id.in_(ids)).all()} if ids else {}
    assessments = _latest_assessments(db, ids)
    sectors = {s.id: s.name for s in db.query(Sector).all()}
    potential = {
        bid for bid, b in businesses.items()
        if b.crm_added_at is not None or (_has_real_opportunity(assessments.get(bid)) and assess_business(b, sectors.get(b.sector_id)).eligible)
    }
    ranks = _reached_ranks(db, list(potential))
    counts = [len(businesses), len(potential)] + [sum(1 for bid in potential if ranks[bid] >= k) for k in (1, 2, 3, 4)]
    labels = ["Analiz", "Potansiyel", *FUNNEL_STEPS]
    steps = [
        {"key": key, "label": label, "count": n, "rate_from_previous": _rate(n, counts[i - 1]) if i else None, "rate_from_analysis": _rate(n, counts[0]) if i else None}
        for i, (key, label, n) in enumerate(zip(["analysis", "potential", "contacted", "interested", "offer", "won"], labels, counts))
    ]
    offered = [b for bid, b in businesses.items() if bid in potential and ranks[bid] >= 3]
    won = [b for b in offered if b.crm_stage == "Kazanıldı"]
    return {
        "period": period, "label": PERIODS[period], "steps": steps,
        "offer_total": float(sum(b.offer_amount or 0 for b in offered)), "offer_count": len(offered), "offer_amount_missing": sum(1 for b in offered if b.offer_amount is None),
        "won_total": float(sum(b.sale_amount or 0 for b in won)), "won_count": len(won), "won_amount_missing": sum(1 for b in won if b.sale_amount is None),
        "note": "Kohort: seçilen dönemde analizi tamamlanan firmaların bugüne kadarki ilerleyişi. Teklif = gönderilmiş teklif.",
        "updated_at": now.astimezone(TZ).isoformat(),
    }


# ------------------------------------------------------------------ gelir (hizmet / sektör)
def revenue(db: Session, by: str = "service", period: str = "total", now: datetime | None = None) -> dict:
    """"Para nereden geliyor?": hizmet ya da sektör bazında fırsat / teklif / satış / tutar / ortalama / dönüşüm.

    - fırsat: şu an analizde 🟢 doğrulanmış fırsatı olan (hizmet) ya da gerçek fırsatı olan uygun firma sayısı (anlık durum).
    - teklif / satış: seçilen dönemde o duruma GEÇEN benzersiz firma sayısı; tutar = satış tutarlarının toplamı (girilmemişse 0 ve ayrıca belirtilir).
    - dönüşüm = satış / teklif (teklif ≥ 1 ise). Örneklem küçükse (teklif < MIN_SAMPLE) "yetersiz veri" işareti taşır; sıralama yalnızca veriden gelir.
    """
    if by not in ("service", "sector"):
        raise ValueError("by: service | sector")
    now = now or datetime.now(timezone.utc)
    start, end = period_bounds(now)[period]
    sectors = {s.id: s.name for s in db.query(Sector).all()}

    def event_ids(stages: tuple[str, ...]) -> dict[int, datetime]:
        q = db.query(CrmActivity.business_id, func.max(CrmActivity.created_at)).filter(
            TRANSITION, CrmActivity.to_stage.in_(stages), *_in(CrmActivity.created_at, start, end)).group_by(CrmActivity.business_id)
        return dict(q.all())

    offers = event_ids(("Teklif Gönderildi", "Kazanıldı"))
    wins_events = event_ids(("Kazanıldı",))
    touched = set(offers) | set(wins_events)
    businesses = {b.id: b for b in db.query(Business).filter(Business.id.in_(touched)).all()} if touched else {}
    wins = {bid for bid in wins_events if bid in businesses and businesses[bid].crm_stage == "Kazanıldı"}  # sonradan başka aşamaya alınan kazanç sayılmaz
    assess_ids = list(businesses)
    assessments = _latest_assessments(db, assess_ids)

    def key_of(b: Business) -> str:
        if by == "sector":
            return sectors.get(b.sector_id, UNSPECIFIED)
        return b.interested_service or _primary_service(assessments.get(b.id)) or UNSPECIFIED

    groups: dict[str, dict] = defaultdict(lambda: {"opportunities": 0, "offers": 0, "sales": 0, "amount": 0.0, "amount_missing": 0, "offer_amount": 0.0})
    for bid in offers:
        b = businesses.get(bid)
        if b is not None:
            groups[key_of(b)]["offers"] += 1
            groups[key_of(b)]["offer_amount"] += float(b.offer_amount or 0)
    for bid in wins:
        b = businesses[bid]
        g = groups[key_of(b)]
        g["sales"] += 1
        g["amount"] += float(b.sale_amount or 0)
        g["amount_missing"] += 1 if b.sale_amount is None else 0

    # anlık fırsat sayısı (analizli tüm firmalar)
    analyzed = db.query(Business).filter(Business.status == "analyzed").all()
    all_assess = _latest_assessments(db, [b.id for b in analyzed])
    for b in analyzed:
        a = all_assess.get(b.id)
        if by == "service":
            for svc in _green_services(a):
                groups[svc]["opportunities"] += 1
        elif _has_real_opportunity(a) and assess_business(b, sectors.get(b.sector_id)).eligible:
            groups[sectors.get(b.sector_id, UNSPECIFIED)]["opportunities"] += 1

    rows = []
    for name, g in groups.items():
        with_amount = g["sales"] - g["amount_missing"]
        rows.append({
            "name": name, **{k: g[k] for k in ("opportunities", "offers", "sales", "amount_missing")},
            "amount": round(g["amount"], 2), "offer_amount": round(g["offer_amount"], 2),
            "average": round(g["amount"] / with_amount, 2) if with_amount else None,
            "conversion": _rate(g["sales"], g["offers"]) if g["offers"] >= MIN_SAMPLE else None,
            "sample_note": None if g["offers"] >= MIN_SAMPLE else (NO_DATA if g["offers"] else "Teklif yok"),
        })
    rows.sort(key=lambda r: (-r["amount"], -r["sales"], -r["offers"], -r["opportunities"], r["name"]))
    return {"by": by, "period": period, "label": PERIODS[period], "items": rows, "min_sample": MIN_SAMPLE, "updated_at": now.astimezone(TZ).isoformat(),
            "note": "Sıralama yalnızca girilen satış tutarlarına göredir; hiçbir hizmet/sektör önceden 'en kârlı' sayılmaz."}


# ------------------------------------------------------------------ personel performansı
def staff_performance(db: Session, period: str = "today", now: datetime | None = None) -> dict:
    """Personel bazlı sonuç raporu (aktivite → sonuç). Otomatik başarılı/başarısız etiketi VERİLMEZ; yalnızca sayılar ve oranlar."""
    now = now or datetime.now(timezone.utc)
    start, end = period_bounds(now)[period]
    users = db.query(User).order_by(User.name).all()
    stats = {u.id: defaultdict(float) for u in users}

    analyses = (
        db.query(AnalysisJob.user_id, func.count(AnalysisJob.id))
        .filter(AnalysisJob.status == "completed", AnalysisJob.trigger == "user", AnalysisJob.user_id.isnot(None), *_in(AnalysisJob.completed_at, start, end))
        .group_by(AnalysisJob.user_id).all()
    )
    for uid, n in analyses:
        stats[uid]["analyses"] = n

    acts = db.query(CrmActivity).filter(CrmActivity.user_id.isnot(None), *_in(CrmActivity.created_at, start, end)).all()
    won_ids = {a.business_id for a in acts if a.to_stage == "Kazanıldı" and a.from_stage != a.to_stage}
    won_biz = {b.id: b for b in db.query(Business).filter(Business.id.in_(won_ids)).all()} if won_ids else {}
    followed: dict[int, set[int]] = defaultdict(set)
    delays: dict[int, list[float]] = defaultdict(list)
    for a in acts:
        s = stats.setdefault(a.user_id, defaultdict(float))
        if a.type == "added":
            s["leads_added"] += 1
        moved = a.type == "added" or (a.type in ("status_change", "contact") and a.from_stage != a.to_stage)
        if a.type == "contact" or (moved and a.to_stage == "Arandı"):
            s["contacts"] += 1
            if (a.meta or {}).get("result") == "Ulaşılamadı":
                s["unreachable"] += 1
        if moved:
            if a.to_stage == "Görüşüldü":
                s["interested"] += 1
            if a.to_stage == "Teklif Gönderildi":
                s["offers_sent"] += 1
            if a.to_stage == "Kazanıldı":
                s["won"] += 1
                b = won_biz.get(a.business_id)
                if b is not None and b.crm_stage == "Kazanıldı":
                    s["sales_total"] += float(b.sale_amount or 0)
                    s["sales_amount_missing"] += 1 if b.sale_amount is None else 0
            if a.to_stage == "Kaybedildi":
                s["lost"] += 1
        if a.type == "follow_up_done":
            followed[a.user_id].add(a.business_id)
            s["follow_ups_done"] += 1
            due = (a.meta or {}).get("due_at")
            if due:
                delays[a.user_id].append((a.created_at - datetime.fromisoformat(due)).total_seconds() / 3600)
    now_utc = now
    owned = db.query(Business.crm_owner_id, Business.crm_stage, Business.next_follow_up_at, Business.crm_added_at).filter(Business.crm_added_at.isnot(None), Business.crm_owner_id.isnot(None)).all()
    lead_count: dict[int, int] = defaultdict(int)
    overdue: dict[int, int] = defaultdict(int)
    for owner, stage, nxt, _ in owned:
        if stage in OPEN_STAGES:
            lead_count[owner] += 1
        if nxt is not None and stage in OPEN_STAGES and nxt.astimezone(TZ).date() < now_utc.astimezone(TZ).date():
            overdue[owner] += 1

    rows = []
    for u in users:
        s = stats[u.id]
        d = delays.get(u.id, [])
        row = {
            "user_id": u.id, "name": u.name, "role": u.role, "is_active": u.is_active,
            "analyses": int(s["analyses"]), "leads_added": int(s["leads_added"]), "assigned_leads": lead_count.get(u.id, 0),
            "contacts": int(s["contacts"]), "unreachable": int(s["unreachable"]), "interested": int(s["interested"]),
            "offers_sent": int(s["offers_sent"]), "won": int(s["won"]), "lost": int(s["lost"]),
            "sales_total": round(s["sales_total"], 2), "sales_amount_missing": int(s["sales_amount_missing"]),
            "followed_customers": len(followed.get(u.id, ())), "follow_ups_done": int(s["follow_ups_done"]),
            "overdue_follow_ups": overdue.get(u.id, 0),  # anlık (dönemden bağımsız): şu an geciken açık takipler
            "avg_follow_delay_hours": round(sum(d) / len(d), 1) if d else None,
            "conversion_offer_to_won": _rate(int(s["won"]), int(s["offers_sent"])) if s["offers_sent"] >= 1 else None,
        }
        if u.is_active or any(row[k] for k in ("analyses", "leads_added", "contacts", "interested", "offers_sent", "won", "lost", "follow_ups_done")):
            rows.append(row)
    return {"period": period, "label": PERIODS[period], "items": rows, "updated_at": now.astimezone(TZ).isoformat(),
            "note": "Rakamlar personelin kayıtlı işlemlerinden gelir; otomatik başarı/başarısızlık değerlendirmesi yapılmaz. Dönüşüm = kazanılan / gönderilen teklif (aynı dönemde)."}


# ------------------------------------------------------------------ dönemsel özet + öneriler
def overview(db: Session, period: str = "today", now: datetime | None = None) -> dict:
    """Yönetici raporu: analiz · yeni potansiyel · arama · görüşme · teklif · satış (+ hizmet/sektör/personel kırılımı)."""
    now = now or datetime.now(timezone.utc)
    start, end = period_bounds(now)[period]
    q = lambda *stages: db.query(func.count(func.distinct(CrmActivity.business_id))).filter(TRANSITION, CrmActivity.to_stage.in_(stages), *_in(CrmActivity.created_at, start, end)).scalar() or 0
    contacted = (
        db.query(func.count(func.distinct(CrmActivity.business_id)))
        .filter(or_(CrmActivity.type == "contact", and_(TRANSITION, CrmActivity.to_stage == "Arandı")), *_in(CrmActivity.created_at, start, end)).scalar() or 0
    )
    report = analysis_report(db, now)[period]
    added = db.query(func.count(func.distinct(CrmActivity.business_id))).filter(CrmActivity.type == "added", *_in(CrmActivity.created_at, start, end)).scalar() or 0
    won_ids = [r[0] for r in db.query(CrmActivity.business_id).filter(TRANSITION, CrmActivity.to_stage == "Kazanıldı", *_in(CrmActivity.created_at, start, end)).distinct().all()]
    won = db.query(Business).filter(Business.id.in_(won_ids), Business.crm_stage == "Kazanıldı").all() if won_ids else []
    return {
        "period": period, "label": PERIODS[period], "updated_at": now.astimezone(TZ).isoformat(),
        "metrics": {
            "analyses": report["analyses"], "analyzed_businesses": report["businesses"], "new_leads": added,
            "contacts": contacted, "interested": q("Görüşüldü"), "offers_sent": q("Teklif Gönderildi"),
            "won": len(won), "won_total": float(sum(b.sale_amount or 0 for b in won)), "won_amount_missing": sum(1 for b in won if b.sale_amount is None),
        },
        "by_service": revenue(db, "service", period, now)["items"], "by_sector": revenue(db, "sector", period, now)["items"],
        "by_staff": staff_performance(db, period, now)["items"],
    }


def suggestions(db: Session, now: datetime | None = None) -> dict:
    """Nesnel, veriye dayalı öneriler. Örneklem yeterli değilse öneri üretilmez ('Yeterli veri bulunmuyor.'); tahmin/garanti içermez."""
    now = now or datetime.now(timezone.utc)
    items: list[dict] = []
    overdue = sum(1 for b in db.query(Business).filter(Business.crm_added_at.isnot(None), Business.next_follow_up_at.isnot(None), Business.crm_stage.in_(OPEN_STAGES)).all()
                  if follow_up_state(b, now) == "overdue")
    if overdue:
        items.append({"kind": "overdue", "text": f"{overdue} açık takip gecikmiş durumda; öncelikle bunların tamamlanması önerilir."})
    f = funnel(db, "total", now)
    steps = f["steps"]
    drops = [(steps[i]["label"], steps[i + 1]["label"], steps[i + 1]["rate_from_previous"], steps[i]["count"]) for i in range(1, len(steps) - 1)
             if steps[i]["count"] >= MIN_SAMPLE and steps[i + 1]["rate_from_previous"] is not None]
    if drops:
        a, b, rate, n = min(drops, key=lambda d: d[2])
        items.append({"kind": "funnel", "text": f"Hunide en düşük geçiş oranı {a} → {b} adımında: %{rate} ({n} firmadan)."})
    for by, label in (("service", "Hizmet"), ("sector", "Sektör")):
        rows = [r for r in revenue(db, by, "total", now)["items"] if r["conversion"] is not None and r["name"] != UNSPECIFIED]
        if rows:
            best = max(rows, key=lambda r: (r["conversion"], r["sales"]))
            items.append({"kind": f"best_{by}", "text": f"{label} bazında en yüksek teklif→satış dönüşümü: {best['name']} (%{best['conversion']}, {best['offers']} teklif). Örneklem sınırlıdır; tek başına karar dayanağı yapmayın."})
    if not any(i["kind"] in ("funnel", "best_service", "best_sector") for i in items):
        items.append({"kind": "no_data", "text": NO_DATA + f" (Oran/karşılaştırma için en az {MIN_SAMPLE} kayıt gerekir.)"})
    return {"items": items, "updated_at": now.astimezone(TZ).isoformat()}
