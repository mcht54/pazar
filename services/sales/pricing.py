"""Hizmet fiyat aralıkları (Yönetim → Hizmet ve Fiyat Ayarları).

KURALLAR
- Kodda SABİT FİYAT YOKTUR. Fiyatlar yalnızca yöneticinin girdiği `service_prices` kayıtlarıdır; girilmemişse arayüz "Fiyatlandırma yapılmadı" der.
- Tahmini değer KESİN TEKLİF DEĞİLDİR: yönetici aralığından türetilen, satış önceliği/planlaması içindir. Kapsam, adet ve sektöre göre değişir.
- Pasif (is_active=False) hizmetler tahmini paket ve raporlara dahil edilmez.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from packages.db.models import ServiceCatalog, ServicePrice, User

NOT_PRICED = "Fiyatlandırma yapılmadı"
DISCLAIMER = "Tahmini değer kesin teklif değildir; kapsam, adet ve sektöre göre değişir."


def _num(value) -> float | None:
    return float(value) if value is not None else None


def list_prices(db: Session) -> list[dict]:
    """Katalogdaki TÜM hizmetler + (varsa) yöneticinin girdiği fiyat aralığı."""
    prices = {p.service_id: p for p in db.query(ServicePrice).all()}
    out = []
    for svc in db.query(ServiceCatalog).order_by(ServiceCatalog.id).all():
        p = prices.get(svc.id)
        out.append({
            "service_id": svc.id, "service_name": svc.service_name,
            "min_price": _num(p.min_price) if p else None, "max_price": _num(p.max_price) if p else None, "default_price": _num(p.default_price) if p else None,
            "is_active": p.is_active if p else True, "priced": bool(p and (p.default_price is not None or p.min_price is not None or p.max_price is not None)),
            "updated_at": p.updated_at if p else None,
        })
    return out


def price_map(db: Session) -> dict[str, dict]:
    return {row["service_name"]: row for row in list_prices(db)}


def _validate(min_price, max_price, default_price) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    def conv(v, label):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        try:
            d = Decimal(str(v).replace(",", "."))
        except Exception:  # noqa: BLE001
            raise ValueError(f"{label} geçerli bir sayı olmalı.") from None
        if not d.is_finite() or d < 0 or d > Decimal("999999999"):
            raise ValueError(f"{label} 0 ile 999.999.999 arasında olmalı.")
        return d.quantize(Decimal("0.01"))

    lo, hi, df = conv(min_price, "En düşük fiyat"), conv(max_price, "En yüksek fiyat"), conv(default_price, "Varsayılan fiyat")
    if lo is not None and hi is not None and lo > hi:
        raise ValueError("En düşük fiyat, en yüksek fiyattan büyük olamaz.")
    if df is not None and lo is not None and df < lo:
        raise ValueError("Varsayılan fiyat, en düşük fiyattan küçük olamaz.")
    if df is not None and hi is not None and df > hi:
        raise ValueError("Varsayılan fiyat, en yüksek fiyattan büyük olamaz.")
    return lo, hi, df


def save_price(db: Session, user: User, service_id: int, *, min_price, max_price, default_price, is_active: bool) -> dict:
    svc = db.get(ServiceCatalog, service_id)
    if svc is None:
        raise LookupError("Hizmet bulunamadı.")
    lo, hi, df = _validate(min_price, max_price, default_price)
    row = db.query(ServicePrice).filter(ServicePrice.service_id == service_id).first()
    if row is None:
        row = ServicePrice(service_id=service_id)
        db.add(row)
    row.min_price, row.max_price, row.default_price, row.is_active, row.updated_by = lo, hi, df, bool(is_active), user.id
    db.commit()
    return next(r for r in list_prices(db) if r["service_id"] == service_id)


def estimate(service: str, prices: dict[str, dict]) -> dict:
    """Tek hizmet için tahmini değer: {priced, min, max, default, label}. Fiyat yoksa/pasifse priced=False."""
    row = prices.get(service)
    if row is None or not row["is_active"] or not row["priced"]:
        return {"priced": False, "min": None, "max": None, "default": None, "label": NOT_PRICED if row is None or row["is_active"] else "Hizmet pasif"}
    lo, hi, df = row["min_price"], row["max_price"], row["default_price"]
    mid = df if df is not None else (lo if lo is not None else hi)
    lo = lo if lo is not None else mid
    hi = hi if hi is not None else mid
    label = f"{lo:,.0f} – {hi:,.0f} TL".replace(",", ".") if lo != hi else f"{lo:,.0f} TL".replace(",", ".")
    return {"priced": True, "min": lo, "max": hi, "default": mid, "label": label}


def package_estimate(services: list[str], prices: dict[str, dict]) -> dict:
    """Önerilen hizmetlerin toplam tahmini değeri. Fiyatı olmayan hizmetler toplama katılmaz ve ayrıca listelenir (uydurma tutar yok)."""
    priced, unpriced = [], []
    lo = hi = df = 0.0
    for name in services:
        est = estimate(name, prices)
        if est["priced"]:
            priced.append({"service": name, **est})
            lo, hi, df = lo + est["min"], hi + est["max"], df + est["default"]
        else:
            unpriced.append(name)
    return {
        "services": services, "priced": priced, "unpriced": unpriced,
        "min": lo if priced else None, "max": hi if priced else None, "default": df if priced else None,
        "label": (f"{lo:,.0f} – {hi:,.0f} TL".replace(",", ".") if lo != hi else f"{lo:,.0f} TL".replace(",", ".")) if priced else NOT_PRICED,
        "disclaimer": DISCLAIMER,
    }
