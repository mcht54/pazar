"""Araştırma katmanı ile veritabanı/iş mantığı arasındaki köprü: sorgu kurma, önbellek, sonucu işletmeye uygulama."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from packages.db.models import Business, BusinessResearch, Region, Sector
from packages.localization import fold
from services.research.models import BusinessQuery
from services.research.normalize import normalize_phone
from services.hybrid.api_settings import active_key as google_api_active_key
from services.research.pipeline import ResearchResult, research_business

CACHE_DAYS = 7


def listing_snapshot(business: Business) -> dict:
    """Keşif anındaki BAĞIMSIZ OLMAYAN kayıt. Google Haritalar keşfinde Google'ın kendi listesi bağımsız bir kaynak sayılmaz (kendini
    doğrulama olurdu), bu yüzden yalnızca ad döner. Yalnızca eski (OpenStreetMap) kayıtlarda adres/telefon/site gibi değerler vardır;
    araştırma Business alanlarını doğrulanmış değerlerle güncellediği için bu değerler ilk araştırmada source_profile['listing'] altında
    dondurulur."""
    profile = business.source_profile or {}
    if profile.get("listing"):
        return profile["listing"]
    if profile.get("osm"):  # dondurulmuş eski kayıtlar
        return profile["osm"]
    if business.discovery_source != "osm_overpass":
        return {"name": business.name}
    return {
        "name": business.name,
        "address": business.address,
        "phone": business.phone,
        "website": business.website,
        "email": business.email,
        "hours": business.opening_hours,
        "category": business.category_label,
        "social": profile.get("social") or {},
    }


def build_query(db: Session, business: Business, listing: dict) -> BusinessQuery:
    sector = db.get(Sector, business.sector_id)
    region = db.get(Region, business.region_id)
    place_names = [region.name]
    if region.parent_region_id:
        parent = db.get(Region, region.parent_region_id)
        if parent is not None:
            place_names.append(parent.name)
    generic = set()
    for text in [*place_names, sector.name, *(sector.keyword_variants or [])]:
        generic.update(fold(text).split())
    phone = normalize_phone(listing.get("phone"))
    return BusinessQuery(
        name=listing.get("name") or business.name, place_names=place_names, lat=business.lat, lng=business.lng,
        phones=[phone] if phone else [], address=listing.get("address") or business.address, website=listing.get("website"), email=listing.get("email"),
        category=listing.get("category"), sector_phrases=list(sector.keyword_variants or []), extra_generic=generic,
    )


def latest_research(db: Session, business_id: int) -> BusinessResearch | None:
    return db.query(BusinessResearch).filter_by(business_id=business_id).order_by(BusinessResearch.id.desc()).first()


def get_or_run_research(db: Session, business: Business, *, force: bool = False, use_google: bool = True) -> tuple[BusinessResearch, bool]:
    """Döndürür: (araştırma kaydı, yeni mi çalıştırıldı). Son CACHE_DAYS gün içinde yapılmış araştırma yeniden kullanılır (dış kaynaklara
    gereksiz istek atılmaz)."""
    existing = latest_research(db, business.id)
    if existing and not force and existing.checked_at > datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS):
        return existing, False

    listing = listing_snapshot(business)
    profile = dict(business.source_profile or {})
    profile["listing"] = listing  # keşif kaydı dondurulur
    business.source_profile = profile
    db.flush()

    query = build_query(db, business, listing)
    query.google_url = business.maps_url if business.discovery_source == "google_maps" else None
    result = research_business(query, listing, use_google=use_google, google_api_key=google_api_active_key(db))  # API kapalıysa None → mevcut kaynaklar
    record = store_research(db, business, result)
    return record, True


def store_research(db: Session, business: Business, result: ResearchResult) -> BusinessResearch:
    record = BusinessResearch(business_id=business.id, checked_at=result.checked_at, payload=result.to_dict())
    db.add(record)
    apply_verified_values(business, result)
    db.flush()
    return record


def apply_verified_values(business: Business, result: ResearchResult) -> None:
    """Doğrulanmış/çelişkisiz değerleri işletme alanlarına yazar. Değer bulunamadıysa mevcut alan silinmez ama YENİ değer de uydurulmaz."""
    v = result.verdicts
    g = result.google

    def take(key: str):
        verdict = v.get(key)
        return verdict.value if verdict and verdict.value and verdict.status in ("dogrulandi", "celiskili", "tek_kaynak") else None

    if take("address"):
        business.address = v["address"].value
    if take("phone"):
        business.phone = v["phone"].value
    if take("website"):
        business.website = v["website"].value
    if take("email"):
        business.email = v["email"].value
    if g:
        if g.rating is not None:
            business.google_rating = g.rating
        if g.review_count is not None:
            business.google_review_count = g.review_count
        if g.category:
            business.category_label = g.category
        if g.hours_text:
            business.opening_hours = g.hours_text
        if g.url and "/maps/place/" in g.url:
            business.maps_url = g.url
        if g.last_review_at:
            business.last_review_at = g.last_review_at
        if g.lat is not None and g.lng is not None:
            business.lat, business.lng = g.lat, g.lng
    business.source_checked_at = result.checked_at
