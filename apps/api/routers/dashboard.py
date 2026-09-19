from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.deps import require
from apps.api.routers.businesses import _build_business_out, _latest_assessments, _load_extras, _presentation_maps
from apps.api.schemas import BusinessOut
from packages.crm import CALLABLE_STAGES
from packages.db.base import get_db
from packages.db.models import Business, User
from services.rule_engine.prospect import assess_business

router = APIRouter(prefix="/api/dashboard", tags=["panel"], dependencies=[Depends(require("dashboard"))])

SCAN_LIMIT = 600  # en yüksek puanlı bu kadar aday taranır; uygun olmayanlar elendikten sonra ilk `limit` kadarı döner


@router.get("/today", response_model=list[BusinessOut])
def today(limit: int = 10, min_score: int = 25, user: User = Depends(require("dashboard")), db: Session = Depends(get_db)):
    """'Bugünün potansiyel müşterileri': analiz edilmiş, henüz kapanmamış (aranacak/yeni/takipte) ve satış puanı yüksek işletmeler.

    Sıralama: satış puanı (yüksekten düşüğe); telefonu olanlar eşitlikte öne alınır. Hiçbir değer uydurulmaz; veri yoksa liste boş döner.
    Mchttasarım'a gerçek satış fırsatı olmayan kayıtlar (kendisi, rakip firmalar, kamu kurumları/devlet okulları) listelenmez;
    karar Google kategorisi + sektör + işletme adı birlikte değerlendirilerek verilir (bkz. services/rule_engine/prospect.py).
    """
    limit = max(1, min(limit, 50))
    candidates = (
        db.query(Business)
        .filter(Business.status == "analyzed", Business.crm_stage.in_(CALLABLE_STAGES), Business.opportunity_score_total >= min_score)
        .order_by(Business.opportunity_score_total.desc(), Business.id.desc())
        .limit(SCAN_LIMIT)
        .all()
    )
    assessments = _latest_assessments(db, [b.id for b in candidates])
    sector_names, region_labels, service_names = _presentation_maps(db)
    candidates = [
        b for b in candidates
        if b.id in assessments and assessments[b.id].level != "Belirsiz" and assess_business(b, sector_names.get(b.sector_id)).eligible
    ]
    def priority_of(b: Business) -> float:
        pr = ((assessments[b.id].payload or {}).get("priority") or {}).get("value")
        return pr if pr is not None else float(b.opportunity_score_total or 0)

    # Bugünün potansiyel müşterileri: satış ÖNCELİĞİNE göre (yalnızca skora değil); eşitlikte telefonu olan önde
    candidates.sort(key=lambda b: (-priority_of(b), 0 if b.phone else 1, b.id))
    top = candidates[:limit]
    extras = _load_extras(db, top, user)
    return [
        _build_business_out(b, sector_names=sector_names, region_labels=region_labels, service_names=service_names, assessment=assessments[b.id], extras=extras)
        for b in top
    ]
