"""Bir işletmenin çok kaynaklı araştırması: Google Haritalar → Bing Haritalar → arama → resmi web sitesi → sosyal medya → çapraz doğrulama.

Her kaynağın durumu (KONTROL EDİLDİ / ERİŞİLEMEDİ / EŞLEŞME YOK) kaydedilir ve arayüzde teknik olarak gösterilir. Bir kaynak engellenirse
diğerleri yine denenir ("kısıtlamayı bahane edip araştırmayı bırakma"); ama engel ASLA aşılmaya çalışılmaz ve veri uydurulmaz.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.integrations.website_crawler.real_crawler import RealWebsiteCrawler
from services.research import bing_maps, google_api, google_maps
from services.research.browser import SourceBlocked, SourceError
from services.research.crosscheck import CrossInputs, FieldVerdict, build_verdicts
from services.research.models import (
    SOURCE_BLOCKED,
    SOURCE_CHECKED,
    SOURCE_NO_MATCH,
    SOURCE_SKIPPED,
    BusinessQuery,
    DirectoryProfile,
    SourceStatus,
)
from services.research.normalize import normalize_phone
from services.research.site_finder import SiteCandidate, find_official_site
from services.research.social import SocialFinding, collect_social
from services.research.web_search import (
    BING_SEARCH,
    GOOGLE_SEARCH,
    bing_search,
    google_search,
    google_search_status,
)

SOURCE_LABELS = {
    "google_maps": "Google İşletme Profili (Haritalar)",
    "google_api": "Google Places API",
    "google_search": "Google Arama",
    "bing_maps": "Bing Haritalar",
    "bing_search": "Bing Arama",
    "website": "Resmi Web Sitesi",
    "listing": "Keşif kaydı (eski OpenStreetMap verisi)",
}


@dataclass
class ResearchResult:
    checked_at: datetime
    sources: list[SourceStatus]
    google: DirectoryProfile | None = None
    google_api: DirectoryProfile | None = None  # Places API profili (yalnızca API aktifse); Maps profilinin yerine geçmez, tamamlar
    bing: DirectoryProfile | None = None
    site: SiteCandidate | None = None
    candidates: list[SiteCandidate] = field(default_factory=list)
    social: list[SocialFinding] = field(default_factory=list)
    verdicts: dict[str, FieldVerdict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at.isoformat(),
            "sources": [s.to_dict() for s in self.sources],
            "google": self.google.to_dict() if self.google else None,
            "google_api": self.google_api.to_dict() if self.google_api else None,
            "bing": self.bing.to_dict() if self.bing else None,
            "site": self.site.to_dict() if self.site else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "social": [s.to_dict() for s in self.social],
            "verdicts": {k: v.to_dict() for k, v in self.verdicts.items()},
            "notes": self.notes,
        }


def _status(key: str, status: str, detail: str = "") -> SourceStatus:
    return SourceStatus(key=key, label=SOURCE_LABELS[key], status=status, detail=detail, checked_at=datetime.now(timezone.utc))


def _guard(key: str, func):
    """Kaynak çağrısını çalıştırır. Döndürür: (sonuç | None, hata durumu | None)."""
    try:
        return func(), None
    except SourceBlocked as exc:
        return None, _status(key, SOURCE_BLOCKED, f"Erişim engellendi: {exc.reason}. Engel aşılmaya çalışılmadı.")
    except SourceError as exc:
        return None, _status(key, SOURCE_BLOCKED, f"Kaynak açılamadı: {exc.reason}")
    except Exception as exc:  # Playwright kurulu değil, tarayıcı çöktü vb. — araştırma diğer kaynaklarla sürer
        return None, _status(key, SOURCE_BLOCKED, f"Beklenmeyen hata ({type(exc).__name__}): {str(exc)[:120]}")


def research_business(query: BusinessQuery, listing: dict, *, crawler: RealWebsiteCrawler | None = None, use_google: bool = True,
                      google_api_key: str | None = None) -> ResearchResult:
    """Tek işletmeyi araştırır. `listing`: keşif anındaki bağımsız-olmayan kayıt (yalnızca eski OpenStreetMap kayıtlarında dolu; Google keşfinde yalnızca ad)."""
    crawler = crawler or RealWebsiteCrawler()
    sources: list[SourceStatus] = []
    if any(listing.get(k) for k in ("address", "phone", "website", "email")):  # yalnızca eski OpenStreetMap kayıtları
        sources.append(_status("listing", SOURCE_CHECKED, "Eski keşif kaydı (OpenStreetMap): tek başına doğrulanmış sayılmaz."))
    notes: list[str] = []

    # ------------------------------------------------------------- 1) Google Haritalar (birincil)
    google: DirectoryProfile | None = None
    google_note = ""
    if use_google:
        result, error = _guard("google_maps", lambda: google_maps.lookup(query, deep=True))
        if error:
            sources.append(error)
            google_note = error.detail
        else:
            google, _candidates, google_note = result
            sources.append(_status("google_maps", SOURCE_CHECKED if google else SOURCE_NO_MATCH, google_note))
    else:
        sources.append(_status("google_maps", SOURCE_SKIPPED, "Bu çalıştırmada Google Haritalar sorgulanmadı."))
        google_note = "Google Haritalar sorgulanmadı."

    # ------------------------------------------------------------- 1b) Google Places API (YALNIZCA yönetici aktifleştirdiyse; TAMAMLAYICI kaynak)
    # API başarısız olursa hata durumu kaydedilir ve araştırma mevcut kaynaklarla EKSİKSİZ sürer (geri dönüş).
    api_profile: DirectoryProfile | None = None
    api_for_crosscheck: DirectoryProfile | None = None
    filled: dict = {}
    if google_api_key:
        result, error = _guard("google_api", lambda: google_api.lookup(query, google_api_key))
        if error:
            sources.append(error)
        else:
            api_profile, api_note = result
            sources.append(_status("google_api", SOURCE_CHECKED if api_profile else SOURCE_NO_MATCH, api_note))
    else:
        sources.append(_status("google_api", SOURCE_SKIPPED, "Google API bağlı/aktif değil; mevcut kaynaklar (Google Haritalar, Bing, web sitesi) kullanıldı."))
    if api_profile is not None:
        if google is None:
            google, google_note = api_profile, "Google Haritalar okunamadı/eşleşmedi; Google Places API kaydı kullanıldı. " + google_note  # geri dönüş tamamlaması
        else:
            api_for_crosscheck = api_profile  # bağımsız kaynak olarak çapraz doğrulamaya girer
            filled = google_api.merge_into_maps(google, api_profile)  # yalnızca Maps'te BOŞ olan alanlar tamamlanır

    # ------------------------------------------------------------- 2) Bing Haritalar (bağımsız ikinci dizin)
    bing: DirectoryProfile | None = None
    result, error = _guard("bing_maps", lambda: bing_maps.lookup(query))
    if error:
        sources.append(error)
    else:
        bing, note = result
        sources.append(_status("bing_maps", SOURCE_CHECKED if bing else SOURCE_NO_MATCH, note))

    # ------------------------------------------------------------- 3) resmi web sitesi (dizinler → OSM → alan adı → arama)
    known_phones = [p for p in [normalize_phone(query.phones[0]) if query.phones else None, normalize_phone(google.phone) if google else None,
                                normalize_phone(api_for_crosscheck.phone) if api_for_crosscheck else None, normalize_phone(bing.phone) if bing else None] if p]
    known_phones = list(dict.fromkeys(known_phones))
    known_address = (google.address if google else None) or (api_for_crosscheck.address if api_for_crosscheck else None) or (bing.address if bing else None) or query.address

    known_sites: list[tuple[str, str]] = []
    for origin, profile in ((getattr(google, "source", "google_maps"), google), ("google_api", api_for_crosscheck), ("bing_maps", bing)):
        if profile and profile.website:
            known_sites.append((origin, profile.website))
    if listing.get("website"):
        known_sites.append(("listing", listing["website"]))

    search_state = {"bing_used": False, "google_hits": None}

    def search_fn(text: str):
        # önce Google Arama (erişilebilirse), sonra Bing
        state, _detail = google_search_status()
        hits: list = []
        if state != "erisilemedi":
            try:
                hits = google_search(text)
                search_state["google_hits"] = len(hits)
            except SourceBlocked:
                pass
            except SourceError:
                pass
        if not hits:
            search_state["bing_used"] = True
            hits = bing_search(text)
        return hits

    def find():
        return find_official_site(query, known_sites, known_phones, known_address, crawler=crawler,
                                  extra_urls=list(google.extra_links) if google else [], search_fn=search_fn)

    found, error = _guard("bing_search", find)
    site, candidates, site_notes = (None, [], [])
    if error:
        # arama motoru hatası site bulmayı bitirmesin: aramasız yeniden dene
        found, _ = _guard("website", lambda: find_official_site(query, known_sites, known_phones, known_address, crawler=crawler,
                                                                  extra_urls=list(google.extra_links) if google else [], search_fn=None))
        sources.append(error)
    if found:
        site, candidates, site_notes = found
    notes.extend(site_notes)

    # arama motoru kaynak durumları
    g_state, g_detail = google_search_status()
    if search_state["google_hits"] is not None:
        sources.append(_status("google_search", SOURCE_CHECKED, f"Google Arama erişilebilir; {search_state['google_hits']} sonuç okundu."))
    elif g_state == "erisilemedi":
        sources.append(_status("google_search", SOURCE_BLOCKED, g_detail))
    else:
        sources.append(_status("google_search", SOURCE_SKIPPED, "Web sitesi dizin kayıtlarından bulunduğu için arama gerekmedi."))
    if search_state["bing_used"] and not error:
        sources.append(_status("bing_search", SOURCE_CHECKED, "Bing araması yapıldı; sonuçlar yalnızca aday sayıldı ve içerikle doğrulandı."))
    elif not error:
        sources.append(_status("bing_search", SOURCE_SKIPPED, "Web sitesi dizin kayıtlarından bulunduğu için arama gerekmedi."))

    if site is None and known_sites:
        sources.append(_status("website", SOURCE_BLOCKED, "Kayıtlı web sitesi(ler) açılamadı: " + "; ".join(f"{c.url}: {', '.join(c.evidence)}" for c in candidates if c.verdict == "erisilemedi")[:300]))
    elif site is None:
        sources.append(_status("website", SOURCE_CHECKED, "Google/Bing/OSM kayıtlarında ve alan adı/arama adaylarında işletmeye ait doğrulanmış bir web sitesi bulunamadı."))
    else:
        sources.append(_status("website", SOURCE_CHECKED, f"Web sitesi {'doğrulandı' if site.verdict == 'dogrulandi' else 'kayıtta listeli (içerik eşleşmesi zayıf)'}: {site.url}"))

    # ------------------------------------------------------------- 4) sosyal medya
    social = collect_social(listing.get("social") or {}, site.all_signals if site else [], site.verdict if site else None)
    # ------------------------------------------------------------- 5) çapraz doğrulama
    verdicts = build_verdicts(CrossInputs(listing=listing, google=google, bing=bing, site=site, google_checked=google is not None,
                                          google_note=google_note, extra_generic=query.extra_generic, google_api=api_for_crosscheck, filled=filled))
    return ResearchResult(checked_at=datetime.now(timezone.utc), sources=sources, google=google, google_api=api_for_crosscheck, bing=bing, site=site,
                          candidates=candidates, social=social, verdicts=verdicts, notes=notes)
