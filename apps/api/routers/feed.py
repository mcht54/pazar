"""MarkaKarnem aday akışı (salt okunur): GET /api/feed/karne-candidates

MarkaKarnem'in "Günün fırsatı" ve "Haftanın 1.si" seçimleri için Pazar'ın bulduğu işletmeleri verir.
- Yalnızca okur; hiçbir kaydı değiştirmez.
- Paylaşılan gizli anahtarla korunur (KARNE_FEED_TOKEN, başlık: X-Feed-Token). Anahtar tanımlı değilse uç kapalıdır (404).
- CRM'e eklenmiş firmalar (müşteri, teklif, aranacak…) ve rakip ajanslar listeye hiç girmez: onlara fırsat mesajı gitmemeli.
- E-posta, personel notu, teklif/satış tutarı gibi iç alanlar verilmez.
"""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from packages.config import settings
from packages.db.base import get_db
from packages.db.models import Business, Region

router = APIRouter(prefix="/api/feed", tags=["markakarnem-akış"])
AGENCY_TERMS = ("ajans", "reklam", "web tasarım", "dijital pazarlama", "sosyal medya yönetimi", "seo hizmet", "yazılım")


def _authorized(token: str | None) -> None:
    expected = settings.karne_feed_token
    if not expected:
        raise HTTPException(status_code=404, detail="Not Found")
    if not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Yetkisiz")


def _place(region: Region | None) -> tuple[str | None, str | None]:
    """(il, ilçe) adları."""
    if region is None:
        return None, None
    if region.level == "ilce":
        return (region.parent.name if region.parent else None), region.name
    return region.name, None


@router.get("/karne-candidates")
def karne_candidates(
    min_reviews: int = Query(50, ge=0, le=100000),
    min_rating: float = Query(4.0, ge=0, le=5),
    limit: int = Query(300, ge=1, le=1000),
    x_feed_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _authorized(x_feed_token)
    rows = (
        db.query(Business)
        .options(joinedload(Business.sector), joinedload(Business.region).joinedload(Region.parent))
        .filter(Business.crm_added_at.is_(None), Business.google_review_count >= min_reviews, Business.google_rating >= min_rating)
        .order_by(Business.google_review_count.desc(), Business.id)
        .limit(limit)
        .all()
    )
    items = []
    for b in rows:
        name = (b.name or "").casefold()
        if any(term in name for term in AGENCY_TERMS) or any(term in (b.sector.name or "").casefold() for term in AGENCY_TERMS):
            continue
        il, ilce = _place(b.region)
        items.append({
            "id": b.id, "name": b.name, "sector": b.sector.name if b.sector else None, "category": b.category_label,
            "il": il, "ilce": ilce, "address": b.address, "lat": b.lat, "lng": b.lng,
            "phone": b.phone, "website": b.website, "place_id": b.google_place_id, "maps_url": b.maps_url,
            "rating": b.google_rating, "review_count": b.google_review_count,
            "last_review_at": b.last_review_at.isoformat() if b.last_review_at else None,
        })
    return {"items": items}
