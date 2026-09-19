"""Çapraz doğrulama: aynı bilgiyi farklı kaynaklarla karşılaştırıp 🟢 DOĞRULANDI / 🟠 ÇELİŞKİLİ / 🔴 BULUNAMADI kararı verir.

Kurallar:
- DOĞRULANDI  : en az iki bağımsız kaynak aynı değeri veriyor YA DA eşleşmesi kesinleşmiş tek yetkili kaynak (Google/Bing profili,
                doğrulanmış resmi web sitesi) veriyor.
- ÇELİŞKİLİ   : kaynaklar farklı değer veriyor → manuel kontrol gerekli. Her iki değer de gösterilir.
- BULUNAMADI  : erişilebilen hiçbir güvenilir kaynakta yok. Kaynağa erişilemediği için hiç kontrol edilemediyse `checked=False`
                ile ayrıca belirtilir ("kontrol edilemedi").
- TEK KAYNAK  : değer var ama yalnızca güvenilirliği doğrulanmamış tek kaynakta (ör. yalnızca eski keşif kaydı). Uydurma değildir,
                ama doğrulanmış da sayılmaz.
"""

from dataclasses import dataclass, field

from packages.localization import normalize_host, tr_lower
from services.research.models import CONFLICTING, NOT_FOUND, SINGLE_SOURCE, VERIFIED, DirectoryProfile
from services.research.normalize import address_overlap, format_phone, name_similarity, normalize_phone
from services.research.site_finder import REJECTED_HOST_PARTS, SiteCandidate

SOURCE_LABELS = {
    "listing": "Keşif kaydı (eski OpenStreetMap verisi)",
    "google_api": "Google Places API",
    "google_maps": "Google İşletme Profili",
    "bing_maps": "Bing Haritalar",
    "website": "Resmi web sitesi",
}


@dataclass
class FieldVerdict:
    key: str
    label: str
    value: str | None
    status: str
    sources: list[dict] = field(default_factory=list)  # [{"key","label","value","url"}]
    note: str = ""
    checked: bool = True  # False: değeri kontrol edecek yetkili kaynağa erişilemedi

    def to_dict(self) -> dict:
        # `source`: değerin ana kaynağı (google_api | google_maps | bing_maps | website | listing | unknown) — alan bazlı kaynak bilgisi
        primary = self.sources[0]["key"] if self.sources and self.value else "unknown"
        return {"key": self.key, "label": self.label, "value": self.value, "status": self.status, "sources": self.sources,
                "note": self.note, "checked": self.checked, "source": primary}


@dataclass
class CrossInputs:
    listing: dict  # keşif anındaki kayıt (yalnızca eski OpenStreetMap kayıtlarında dolu): name, address, phone, website, email, hours, category
    google: DirectoryProfile | None
    bing: DirectoryProfile | None
    site: SiteCandidate | None
    google_checked: bool  # Google Haritalar okunabildi mi (erişim + arama yapıldı)
    google_note: str = ""
    extra_generic: set[str] = field(default_factory=set)
    # Google Places API (yalnızca yönetici aktifleştirdiyse): BAĞIMSIZ ek kaynak. Maps profili yoksa `google` alanı API profilinin kendisidir
    # (o durumda bu alan None kalır; aynı veri iki kez sayılmaz).
    google_api: DirectoryProfile | None = None
    filled: dict = field(default_factory=dict)  # Maps'te boş olup API'den tamamlanan alanlar: {"rating": "google_api", ...}


def _src(key: str, value, url: str | None = None) -> dict:
    return {"key": key, "label": SOURCE_LABELS[key], "value": value, "url": url}


def _missing_note(inp: CrossInputs, what: str) -> tuple[str, bool]:
    if not inp.google_checked:
        return f"{what} Google İşletme Profili erişilemediği/eşleşmediği için kontrol edilemedi. {inp.google_note}".strip(), False
    return f"{what} erişilebilen kaynaklarda bulunamadı.", True


def _cluster(observations: list[tuple[str, str]], equal) -> list[list[tuple[str, str]]]:
    clusters: list[list[tuple[str, str]]] = []
    for obs in observations:
        for cluster in clusters:
            if equal(cluster[0][1], obs[1]):
                cluster.append(obs)
                break
        else:
            clusters.append([obs])
    return clusters


def _directory_observations(inp: CrossInputs, getter) -> list[tuple[str, str]]:
    out = []
    for key, value in ((_gkey(inp), getter(inp.google)), ("google_api", getter(inp.google_api)), ("bing_maps", getter(inp.bing)), ("listing", getter_listing(inp, getter))):
        if value:
            out.append((key, value))
    return out


def _gkey(inp: "CrossInputs") -> str:
    """`google` profilinin kaynak anahtarı: normalde Google Haritalar; Maps okunamayıp API kullanıldıysa Google API."""
    return getattr(inp.google, "source", None) or "google_maps"


def getter_listing(inp: CrossInputs, getter) -> str | None:
    return getter(inp.listing) if isinstance(inp.listing, dict) else None


def _by_attr(name: str):
    def get(obj):
        if obj is None:
            return None
        return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
    return get


def _site_verified(inp: CrossInputs) -> bool:
    return bool(inp.site and inp.site.verdict == "dogrulandi")


# ----------------------------------------------------------------------------- alanlar
def phone_verdict(inp: CrossInputs) -> FieldVerdict:
    observations = [(k, normalize_phone(v)) for k, v in _directory_observations(inp, _by_attr("phone"))]
    observations = [(k, v) for k, v in observations if v]
    site_phones = inp.site.phones if inp.site else []
    clusters = _cluster(observations, lambda a, b: a == b)

    if not observations:
        if site_phones and inp.site:
            status = VERIFIED if _site_verified(inp) else SINGLE_SOURCE
            note = "Yalnızca resmi web sitesinde görüldü." + ("" if status == VERIFIED else " Site işletmeyle tam doğrulanamadı.")
            return FieldVerdict("phone", "Telefon", format_phone(site_phones[0]), status, [_src("website", format_phone(site_phones[0]), inp.site.url)], note)
        note, checked = _missing_note(inp, "Telefon numarası")
        return FieldVerdict("phone", "Telefon", None, NOT_FOUND, [], note, checked)

    if len(clusters) > 1:
        preferred = next((c for c in clusters if any(k in ("google_maps", "google_api") for k, _ in c)), clusters[0])
        sources = [_src(k, format_phone(v)) for c in clusters for k, v in c]
        return FieldVerdict("phone", "Telefon", format_phone(preferred[0][1]), CONFLICTING, sources,
                            "Kaynaklar farklı numara veriyor — manuel kontrol gerekli.")

    cluster = clusters[0]
    value = cluster[0][1]
    sources = [_src(k, format_phone(v)) for k, v in cluster]
    site_match = value in site_phones
    if site_match and inp.site:
        sources.append(_src("website", format_phone(value), inp.site.url))
    keys = {k for k, _ in cluster}
    agreeing = len(cluster) + (1 if site_match else 0)
    if agreeing >= 2 or keys & {"google_maps", "google_api", "bing_maps"}:
        note = ""
        if site_phones and not site_match:
            others = ", ".join(format_phone(p) for p in site_phones[:3])
            if agreeing >= 2:
                note = f"Web sitesinde farklı numara(lar) da görüldü: {others} (genel merkez/başka birim olabilir)."
            else:
                return FieldVerdict("phone", "Telefon", format_phone(value), CONFLICTING, sources + [_src("website", others, inp.site.url)],
                                    f"Web sitesindeki numara(lar) farklı: {others} — manuel kontrol gerekli.")
        return FieldVerdict("phone", "Telefon", format_phone(value), VERIFIED, sources, note)
    return FieldVerdict("phone", "Telefon", format_phone(value), SINGLE_SOURCE, sources,
                        "Yalnızca keşif kaydında var; başka kaynakla doğrulanamadı.")


def address_verdict(inp: CrossInputs) -> FieldVerdict:
    exclude = inp.extra_generic
    observations = [(k, v) for k, v in _directory_observations(inp, _by_attr("address")) if v]
    site_text = None
    if inp.site:
        for sig in inp.site.all_signals:
            site_text = site_text or sig.address_text or (sig.schema_business or {}).get("address")

    def equal(a: str, b: str) -> bool:
        overlap = address_overlap(a, b, exclude)
        return overlap is None or overlap >= 0.5  # karşılaştırılamayan (çok kısa) adres çelişki sayılmaz

    if not observations:
        if site_text and _site_verified(inp):
            return FieldVerdict("address", "Adres", site_text, VERIFIED, [_src("website", site_text, inp.site.url)], "Yalnızca resmi web sitesinde görüldü.")
        note, checked = _missing_note(inp, "Adres")
        return FieldVerdict("address", "Adres", None, NOT_FOUND, [], note, checked)

    clusters = _cluster(observations, equal)
    preferred_key = next((k for k in ("google_maps", "google_api", "bing_maps", "listing") if any(o[0] == k for o in observations)), observations[0][0])
    display = next(v for k, v in observations if k == preferred_key)
    sources = [_src(k, v) for k, v in observations]
    if len(clusters) > 1:
        return FieldVerdict("address", "Adres", display, CONFLICTING, sources, "Kaynaklardaki adresler birbirinden farklı — manuel kontrol gerekli.")
    keys = {k for k, _ in observations}
    site_ok = site_text is not None and equal(display, site_text) and address_overlap(display, site_text, exclude) is not None
    if site_ok and inp.site:
        sources.append(_src("website", site_text, inp.site.url))
    if len(observations) + (1 if site_ok else 0) >= 2 or keys & {"google_maps", "google_api", "bing_maps"}:
        return FieldVerdict("address", "Adres", display, VERIFIED, sources)
    return FieldVerdict("address", "Adres", display, SINGLE_SOURCE, sources, "Yalnızca keşif kaydında var; başka kaynakla doğrulanamadı.")


def _real_site(url: str | None) -> str | None:
    host = normalize_host(url)
    if not url or not host or any(part in host for part in REJECTED_HOST_PARTS):
        return None
    return url


def website_verdict(inp: CrossInputs) -> FieldVerdict:
    observations = []
    for key, url in ((_gkey(inp), _by_attr("website")(inp.google)), ("google_api", _by_attr("website")(inp.google_api)), ("bing_maps", _by_attr("website")(inp.bing)), ("listing", getter_listing(inp, _by_attr("website")))):
        if _real_site(url):
            observations.append((key, url))
    clusters = _cluster(observations, lambda a, b: normalize_host(a) == normalize_host(b))
    found_by_search = inp.site if inp.site and inp.site.origin in ("domain_guess", "arama") and inp.site.verdict == "dogrulandi" else None

    if not observations:
        if found_by_search:
            return FieldVerdict("website", "Web sitesi", found_by_search.url, VERIFIED, [_src("website", found_by_search.url, found_by_search.url)],
                                "Google/Bing/OSM kayıtlarında yok; site aranarak bulundu ve içeriği işletmeyle eşleştirildi: " + "; ".join(found_by_search.evidence) + ".")
        note, checked = _missing_note(inp, "Web sitesi")
        return FieldVerdict("website", "Web sitesi", None, NOT_FOUND, [], note, checked)

    sources = [_src(k, v, v) for k, v in observations]
    if len(clusters) > 1:
        preferred = next((c for c in clusters if any(k in ("google_maps", "google_api") for k, _ in c)), clusters[0])
        return FieldVerdict("website", "Web sitesi", preferred[0][1], CONFLICTING, sources, "Kaynaklar farklı web sitesi adresi veriyor — manuel kontrol gerekli.")
    value = clusters[0][0][1]
    note = ""
    if inp.site and inp.site.verdict == "dogrulandi":
        sources.append(_src("website", value, inp.site.url))
        note = "Site içeriği işletmeyle eşleşti: " + "; ".join(inp.site.evidence) + "."
    elif inp.site and inp.site.verdict == "listelenmis":
        note = "Sitede işletme adı/telefon/adres eşleşmesi bulunamadı (zincir/marka sitesi olabilir)."
    keys = {k for k, _ in observations}
    if len(observations) >= 2 or keys & {"google_maps", "google_api", "bing_maps"} or (inp.site and inp.site.verdict == "dogrulandi"):
        return FieldVerdict("website", "Web sitesi", value, VERIFIED, sources, note)
    return FieldVerdict("website", "Web sitesi", value, SINGLE_SOURCE, sources, "Yalnızca keşif kaydında var; " + (note or "başka kaynakla doğrulanamadı."))


def email_verdict(inp: CrossInputs) -> FieldVerdict:
    listing_email = (getter_listing(inp, _by_attr("email")) or "").strip().lower() or None
    site_emails = inp.site.emails if inp.site else []
    site_ok = _site_verified(inp)
    if listing_email and listing_email in site_emails:
        return FieldVerdict("email", "E-posta", listing_email, VERIFIED, [_src("listing", listing_email), _src("website", listing_email, inp.site.url)])
    if listing_email and site_emails:
        return FieldVerdict("email", "E-posta", listing_email, CONFLICTING, [_src("listing", listing_email), _src("website", ", ".join(site_emails[:3]), inp.site.url)],
                            "Keşif kaydı ve web sitesi farklı e-posta veriyor — manuel kontrol gerekli.")
    if site_emails:
        status = VERIFIED if site_ok else SINGLE_SOURCE
        return FieldVerdict("email", "E-posta", site_emails[0], status, [_src("website", site_emails[0], inp.site.url)],
                            "" if site_ok else "Site işletmeyle tam doğrulanamadı.")
    if listing_email:
        return FieldVerdict("email", "E-posta", listing_email, SINGLE_SOURCE, [_src("listing", listing_email)], "Yalnızca keşif kaydında var.")
    checked = bool(inp.site and inp.site.all_signals)
    note = "Resmi web sitesinde ve kayıtlarda e-posta bulunamadı." if checked else "E-posta için kontrol edilebilecek doğrulanmış bir web sitesi/kayıt yok."
    return FieldVerdict("email", "E-posta", None, NOT_FOUND, [], note, checked)


def name_verdict(inp: CrossInputs) -> FieldVerdict:
    listing_name = getter_listing(inp, _by_attr("name"))
    names = [(k, v) for k, v in ((_gkey(inp), _by_attr("name")(inp.google)), ("google_api", _by_attr("name")(inp.google_api)), ("bing_maps", _by_attr("name")(inp.bing)), ("listing", listing_name)) if v]
    display = next((v for k, v in names if k in ("google_maps", "google_api")), None) or next((v for k, v in names if k == "bing_maps"), None) or listing_name
    sources = [_src(k, v) for k, v in names]
    directory = [k for k, _ in names if k != "listing"]
    if directory:
        return FieldVerdict("name", "İşletme adı", display, VERIFIED, sources)
    return FieldVerdict("name", "İşletme adı", display, SINGLE_SOURCE, sources, "Yalnızca keşif kaydında var.")


def _google_only(inp: CrossInputs, key: str, label: str, value, *, missing: str, url: str | None = None, allow_zero: bool = False) -> FieldVerdict:
    if inp.google is None:
        note, checked = _missing_note(inp, missing)
        return FieldVerdict(key, label, None, NOT_FOUND, [], note, checked)
    if value is None or value == "" or (value == [] ):
        return FieldVerdict(key, label, None, NOT_FOUND, [], f"Google İşletme Profilinde {tr_lower(missing)} bulunamadı.", True)
    src = inp.filled.get(key) or _gkey(inp)
    note = "Google Haritalar profilinde yoktu; Google Places API'den tamamlandı." if inp.filled.get(key) else ""
    return FieldVerdict(key, label, value if isinstance(value, str) else str(value), VERIFIED, [_src(src, str(value), url or inp.google.url)], note)


def google_field_verdicts(inp: CrossInputs) -> list[FieldVerdict]:
    g = inp.google
    verdicts = [
        _google_only(inp, "rating", "Google puanı", None if g is None or g.rating is None else f"{g.rating:.1f}".replace(".", ","), missing="Google puanı"),
        _google_only(inp, "review_count", "Google yorum sayısı", None if g is None else g.review_count, missing="Yorum sayısı"),
        _google_only(inp, "maps_url", "Google Maps bağlantısı", None if g is None else g.url, missing="Google Maps bağlantısı"),
        _google_only(inp, "description", "İşletme açıklaması", None if g is None else g.description, missing="İşletme açıklaması"),
        _google_only(inp, "attributes", "Hizmetler / özellikler", None if g is None else (", ".join(g.attributes) or None), missing="Hizmetler/özellikler bölümü"),
    ]
    # kategori: Google kategorisi; OSM kategorisi not olarak eklenir
    cat = _google_only(inp, "category", "Kategori", None if g is None else g.category, missing="Kategori")
    listing_cat = getter_listing(inp, _by_attr("category"))
    if cat.status == NOT_FOUND and listing_cat:
        cat = FieldVerdict("category", "Kategori", listing_cat, SINGLE_SOURCE, [_src("listing", listing_cat)], "Yalnızca keşif kaydındaki kategori var; Google kategorisi doğrulanamadı.", cat.checked)
    elif listing_cat and cat.status == VERIFIED:
        cat.note = f"Keşif kaydındaki kategori: {listing_cat}."
    verdicts.append(cat)
    # çalışma saatleri: Google; yoksa OSM (tek kaynak)
    hours = _google_only(inp, "hours", "Çalışma saatleri", None if g is None else g.hours_text, missing="Çalışma saatleri")
    listing_hours = getter_listing(inp, _by_attr("hours"))
    if hours.status == NOT_FOUND and listing_hours:
        hours = FieldVerdict("hours", "Çalışma saatleri", listing_hours, SINGLE_SOURCE, [_src("listing", listing_hours)], "Yalnızca keşif kaydında var.", hours.checked)
    verdicts.append(hours)
    # son yorum (yaklaşık) ve işletme yanıtı
    if g and g.last_review_relative:
        verdicts.append(FieldVerdict("last_review", "Son yorum tarihi", f"{g.last_review_relative} (yaklaşık)", VERIFIED, [_src("google_maps", g.last_review_relative, g.url)],
                                     f"Google'ın '{g.reviews_sort or 'en alakalı'}' sıralamasındaki ilk {g.reviews_sampled} yorumdan; Google göreli tarih verir."))
    else:
        verdicts.append(_google_only(inp, "last_review", "Son yorum tarihi", None, missing="Son yorum tarihi"))
    if g and g.owner_replies is not None and g.reviews_sampled:
        verdicts.append(FieldVerdict("owner_replies", "Yorumlara işletme yanıtı", f"{g.owner_replies}/{g.reviews_sampled} yorumda yanıt var", VERIFIED,
                                     [_src("google_maps", f"{g.owner_replies}/{g.reviews_sampled}", g.url)], "İncelenen son yorumlara göre."))
    else:
        verdicts.append(_google_only(inp, "owner_replies", "Yorumlara işletme yanıtı", None, missing="Yorum yanıtları"))
    verdicts.append(_google_only(inp, "cover_photo", "Kapak fotoğrafı tarihi", None if g is None else g.cover_photo_date, missing="Kapak fotoğrafı tarihi"))
    return verdicts


def build_verdicts(inp: CrossInputs) -> dict[str, FieldVerdict]:
    verdicts = [name_verdict(inp), address_verdict(inp), phone_verdict(inp), website_verdict(inp), email_verdict(inp), *google_field_verdicts(inp)]
    return {v.key: v for v in verdicts}
