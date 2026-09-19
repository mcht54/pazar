from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from apps.api.deps import client_ip, require
from apps.api.schemas import ContactIn, FollowUpComplete
from apps.api.routers.businesses import _build_business_out, _latest_assessments, _load_extras, _presentation_maps
from packages.crm import CRM_STAGES, WORK_ORDER, normalize_stage
from packages.db.base import get_db
from packages.db.models import Business, FollowUp, Region, User
from services import crm_service
from services import follow_up_service as fus
from packages.localization import fold

router = APIRouter(prefix="/api/crm", tags=["crm"], dependencies=[Depends(require("crm_use"))])

SORTS = ("last_action", "stage", "score", "analyzed", "name", "follow_up")
FOLLOW_UP_FILTERS = ("overdue", "today", "upcoming", "none")


def _ts(value: datetime | None) -> float:
    return value.timestamp() if value else 0.0


@router.get("/summary")
def crm_summary(db: Session = Depends(get_db)):
    """Ana sayfadaki 'CRM ÖZETİ': CRM'deki firma sayısı ve duruma göre dağılım (gerçek CRM kayıtlarından)."""
    counts = {stage: 0 for stage in CRM_STAGES}
    for (stage,) in db.query(Business.crm_stage).filter(Business.crm_added_at.isnot(None)).all():
        counts[stage] = counts.get(stage, 0) + 1
    return {"total": sum(counts.values()), "by_stage": counts}


@router.get("")
def list_crm(
    stage: str | None = None,
    q: str | None = None,
    province_id: int | None = None,
    district_id: int | None = None,
    sector_id: int | None = None,
    service: str | None = None,
    user_id: int | None = None,
    sort: str = "last_action",
    follow_up: str | None = None,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require("crm_use")),
    db: Session = Depends(get_db),
):
    """CRM'e alınmış TÜM firmalar (analiz ile CRM ayrıdır: yalnızca CRM'e eklenenler burada listelenir).

    Filtreler: durum, serbest arama (ad/telefon/adres/kategori/not), il, ilçe, sektör, önerilen hizmet. Sıralama: son işlem (varsayılan),
    durum (çalışma sırası: önce Takip Bekliyor), satış puanı, analiz tarihi, ad.
    """
    if stage is not None:
        stage = normalize_stage(stage)
        if stage is None:
            raise HTTPException(status_code=422, detail=f"Geçersiz CRM durumu. Geçerli durumlar: {', '.join(CRM_STAGES)}")
    page, page_size = max(1, page), max(1, min(page_size, 200))
    if follow_up is not None and follow_up not in FOLLOW_UP_FILTERS:
        raise HTTPException(status_code=422, detail=f"Geçersiz takip filtresi. Geçerli: {', '.join(FOLLOW_UP_FILTERS)}")
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail=f"Geçersiz sıralama. Geçerli: {', '.join(SORTS)}")

    all_crm = db.query(Business).filter(Business.crm_added_at.isnot(None)).all()
    assessments = _latest_assessments(db, [b.id for b in all_crm])
    sector_names, region_labels, service_names = _presentation_maps(db)
    regions = {r.id: r for r in db.query(Region).all()}
    extras = _load_extras(db, all_crm, user)
    outs = {
        b.id: _build_business_out(b, sector_names=sector_names, region_labels=region_labels, service_names=service_names, assessment=assessments.get(b.id), extras=extras)
        for b in all_crm
    }

    counts = {s: 0 for s in CRM_STAGES}
    for b in all_crm:
        counts[b.crm_stage] = counts.get(b.crm_stage, 0) + 1

    def in_province(b: Business, pid: int) -> bool:
        region = regions.get(b.region_id)
        return bool(region and (region.id == pid or region.parent_region_id == pid))

    needle = fold(q) if q and q.strip() else None
    digits = "".join(ch for ch in (q or "") if ch.isdigit())
    selected: list[Business] = []
    for b in all_crm:
        out = outs[b.id]
        if stage and b.crm_stage != stage:
            continue
        if province_id is not None and not in_province(b, province_id):
            continue
        if district_id is not None and b.region_id != district_id:
            continue
        if sector_id is not None and b.sector_id != sector_id:
            continue
        if service and out.primary_service != service:
            continue
        if user_id is not None and user_id not in (b.crm_added_by, b.crm_updated_by, b.crm_owner_id):
            continue
        if follow_up is not None and (crm_service.follow_up_state(b) or "none") != follow_up:
            continue
        if needle:
            haystack = fold(" ".join(filter(None, [b.name, b.phone, b.address, b.category_label, out.sector_name, out.region_label, b.staff_note])))
            phone_digits = "".join(ch for ch in (b.phone or "") if ch.isdigit())
            if needle not in haystack and not (len(digits) >= 4 and digits in phone_digits):
                continue
        selected.append(b)

    def stage_rank(b: Business) -> int:
        return WORK_ORDER.index(b.crm_stage) if b.crm_stage in WORK_ORDER else len(WORK_ORDER)

    if sort == "last_action":
        selected.sort(key=lambda b: (-_ts(b.crm_updated_at or b.crm_added_at), b.id))
    elif sort == "stage":
        selected.sort(key=lambda b: (stage_rank(b), -_ts(b.crm_updated_at or b.crm_added_at), b.id))
    elif sort == "follow_up":  # önce gecikenler/en yakın takip; takibi olmayanlar sonda
        selected.sort(key=lambda b: (b.next_follow_up_at is None, b.next_follow_up_at.timestamp() if b.next_follow_up_at else 0, b.id))
    elif sort == "score":
        selected.sort(key=lambda b: (-(outs[b.id].sales_score if outs[b.id].sales_score is not None else -1), -_ts(b.crm_updated_at), b.id))
    elif sort == "analyzed":
        selected.sort(key=lambda b: (-_ts(b.last_analysis_at), b.id))
    else:
        selected.sort(key=lambda b: (fold(b.name), b.id))

    parent_of = {r.id: r.parent_region_id for r in regions.values()}
    provinces: set[tuple[int, str]] = set()
    districts: set[tuple[int, str]] = set()
    for b in all_crm:
        region = regions.get(b.region_id)
        if region is None:
            continue
        parent = regions.get(region.parent_region_id) if region.parent_region_id else None
        provinces.add((parent.id, parent.name) if parent else (region.id, region.name))
        if parent:
            districts.add((region.id, region.name))
    facets = {
        "provinces": [{"id": i, "name": n} for i, n in sorted(provinces, key=lambda x: fold(x[1]))],
        "districts": [{"id": i, "name": n, "province_id": parent_of.get(i)} for i, n in sorted(districts, key=lambda x: fold(x[1]))],
        "sectors": [{"id": i, "name": n} for i, n in sorted({(b.sector_id, outs[b.id].sector_name) for b in all_crm}, key=lambda x: fold(x[1]))],
        "services": sorted({o.primary_service for o in outs.values() if o.primary_service}, key=fold),
        "users": [{"id": uid, "name": name} for uid, name in sorted(
            {(uid, extras["users"].get(uid)) for b in all_crm for uid in (b.crm_added_by, b.crm_updated_by, b.crm_owner_id) if uid and extras["users"].get(uid)}, key=lambda x: fold(x[1]))],
    }
    return {
        "total": len(all_crm),
        "filtered_total": len(selected),
        "page": page, "page_size": page_size, "pages": max(1, -(-len(selected) // page_size)),
        "counts": counts,
        "facets": facets,
        "items": [outs[b.id].model_dump(mode="json") for b in selected[(page - 1) * page_size: page * page_size]],
    }


@router.get("/owners")
def owners(user: User = Depends(require("crm_assign")), db: Session = Depends(get_db)):
    """Sorumlu personel seçimi için aktif kullanıcılar (yalnızca sorumlu atama yetkisi olanlar)."""
    return [{"id": u.id, "name": u.name} for u in db.query(User).filter(User.is_active.is_(True)).order_by(User.name).all()]


@router.get("/services")
def services(db: Session = Depends(get_db)):
    """'İlgilenilen hizmet' seçimi için katalogdaki hizmet adları."""
    from packages.db.models import ServiceCatalog

    return [s.service_name for s in db.query(ServiceCatalog).order_by(ServiceCatalog.id).all()]


@router.get("/follow-ups")
def follow_ups(scope: str = "mine", user_id: int | None = None, user: User = Depends(require("crm_use")), db: Session = Depends(get_db)):
    """Bugünkü / geciken / yaklaşan takipler (Europe/Istanbul takvim günü). `scope=mine` (varsayılan): sorumlusu ben olanlar; `all`: tümü.

    Kapanmış (Kazanıldı/Kaybedildi) kayıtlarda takip tutulmaz. Hiçbir takip otomatik uydurulmaz; yalnızca personelin girdiği tarihler listelenir.
    """
    if scope not in ("mine", "all"):
        raise HTTPException(status_code=422, detail="scope 'mine' ya da 'all' olmalı")
    owner = user_id if user_id is not None else (user.id if scope == "mine" else None)
    pending = db.query(FollowUp.business_id).filter(FollowUp.status == fus.PENDING)
    if owner is not None:
        pending = pending.filter(FollowUp.user_id == owner)  # takipten sorumlu kullanıcı (varsayılan: firmanın sorumlusu / takibi oluşturan)
    query = db.query(Business).filter(Business.crm_added_at.isnot(None), Business.next_follow_up_at.isnot(None), Business.id.in_(pending))
    rows = query.order_by(Business.next_follow_up_at).all()
    assessments = _latest_assessments(db, [b.id for b in rows])
    sector_names, region_labels, service_names = _presentation_maps(db)
    extras = _load_extras(db, rows, user)
    now = datetime.now(timezone.utc)
    groups: dict[str, list] = {"overdue": [], "today": [], "tomorrow": [], "week": [], "upcoming": []}
    week_start, week_end = fus.week_bounds(now)
    tomorrow_start, tomorrow_end = fus.range_bounds("tomorrow", now)
    for b in rows:
        state = crm_service.follow_up_state(b, now)
        if state is None:
            continue
        out = _build_business_out(b, sector_names=sector_names, region_labels=region_labels, service_names=service_names, assessment=assessments.get(b.id), extras=extras).model_dump(mode="json")
        groups[state].append(out)
        if tomorrow_start <= b.next_follow_up_at < tomorrow_end:
            groups["tomorrow"].append(out)
        if week_start <= b.next_follow_up_at < week_end:
            groups["week"].append(out)  # bu hafta: bugün → gelecek Pazartesi (bugünkü ve yarınki takipler de dahildir)
    return {
        "counts": {k: len(v) for k, v in groups.items()}, "overdue": groups["overdue"], "today": groups["today"], "tomorrow": groups["tomorrow"],
        "week": groups["week"], "upcoming": groups["upcoming"][:50],
        "results": crm_service.FOLLOW_UP_RESULTS, "updated_at": now.astimezone(crm_service.TZ).isoformat(),
    }


@router.post("/{business_id}/follow-up/complete")
def complete_follow_up(business_id: int, payload: FollowUpComplete, request: Request, user: User = Depends(require("crm_use")), db: Session = Depends(get_db)):
    """Takibi tamamlar: sonuç + not kaydedilir, istenirse yeni takip tarihi planlanır."""
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="İşletme bulunamadı")
    try:
        crm_service.complete_follow_up(db, business, payload.result, payload.note, payload.next_follow_up_at, user=user, ip=client_ip(request))
    except crm_service.CrmError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return crm_service.crm_state(db, business)


@router.post("/{business_id}/contact")
def log_contact(business_id: int, payload: ContactIn, request: Request, user: User = Depends(require("crm_use")), db: Session = Depends(get_db)):
    """İletişim geçmişine kayıt: arama/WhatsApp/e-posta/yüz yüze + sonuç (ör. Ulaşılamadı, Görüşüldü, İlgileniyor, Teklif istendi). Aşama sonuca göre güncellenir."""
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="İşletme bulunamadı")
    try:
        crm_service.log_contact(db, business, payload.channel, payload.result, payload.note, user=user, ip=client_ip(request))
    except crm_service.CrmError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return crm_service.crm_state(db, business)


@router.get("/meta")
def crm_meta():
    """Arayüz için sabit listeler: aşamalar, iletişim türleri/sonuçları, kayıp nedenleri."""
    from packages.crm import CONTACT_CHANNELS, CONTACT_RESULTS, LOST_REASONS

    return {"stages": CRM_STAGES, "channels": [{"key": k, "label": v} for k, v in CONTACT_CHANNELS.items()], "results": CONTACT_RESULTS, "lost_reasons": LOST_REASONS}
