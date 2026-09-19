from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.deps import require
from packages.db.base import get_db
from packages.db.models import Business, Region, Sector
from services.knowledge.guides import CATEGORIES, GUIDES, render_guide

router = APIRouter(prefix="/api/guides", tags=["çözüm rehberi"], dependencies=[Depends(require("guides"))])


@router.get("")
def list_guides():
    """Çözüm Rehberi kütüphanesi: kategorilere göre tüm sorun rehberleri."""
    return {
        "categories": CATEGORIES,
        "guides": [{"id": g.id, "category": g.category, "title": g.title, "services": list(g.services)} for g in GUIDES.values()],
    }


@router.get("/{guide_id}")
def get_guide(guide_id: str, business_id: int | None = None, sector_id: int | None = None, db: Session = Depends(get_db)):
    """Rehberi getirir. business_id verilirse metinler o işletmenin gerçek adı/bölgesiyle ve (varsa) analizde bulunan kanıtlarla doldurulur;
    sector_id verilirse sektöre göre uyarlanır. İkisi de yoksa genel ifadeler kullanılır."""
    guide = GUIDES.get(guide_id)
    if guide is None:
        raise HTTPException(status_code=404, detail="Rehber bulunamadı")
    business_name = place = sector_name = phrase = None
    evidence: list[dict] = []
    if business_id is not None:
        business = db.get(Business, business_id)
        if business is None:
            raise HTTPException(status_code=404, detail="İşletme bulunamadı")
        sector_id = business.sector_id
        region = db.get(Region, business.region_id)
        business_name, place = business.name, region.name
        from apps.api.routers.businesses import _latest_assessments

        assessment = _latest_assessments(db, [business_id]).get(business_id)
        if assessment:
            wanted = {k.split(".", 1)[1] for k in guide.check_keys}
            for gap in (assessment.payload or {}).get("gaps", []):
                if gap["key"] in wanted:
                    evidence.append({"problem": gap["value"], "evidence": gap.get("detail", ""), "why": gap.get("why", ""), "severity": gap["severity"], "confidence": gap["confidence"]})
    if sector_id is not None:
        sector = db.get(Sector, sector_id)
        if sector:
            sector_name, phrase = sector.name, (sector.keyword_variants or [sector.name.lower()])[0]
    rendered = render_guide(guide, business=business_name, place=place, sector=sector_name, phrase=phrase)
    rendered["business_evidence"] = evidence  # bu işletmede analizde gerçekten tespit edilen kanıtlar (yoksa boş)
    return rendered
