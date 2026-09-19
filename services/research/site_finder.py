"""İşletmenin RESMİ web sitesini bulma ve doğrulama.

Sıra: (1) eşleşen Google/Bing profilinde listelenen site, (2) keşif kaydındaki site, (3) işletme adından türetilen alan adı adayları,
(4) web araması sonuçları. Adaylar (1) ve (2) dışında içerik doğrulamasından geçmeden ASLA kabul edilmez:
site içinde işletme adı + (telefon | adres | şehir) eşleşmelidir. Yanlış firmanın sitesi işletmeye bağlanmaz.
"""

import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from packages.localization import fold, normalize_host
from services.integrations.website_crawler.base import WebsiteSignals
from services.integrations.website_crawler.real_crawler import RealWebsiteCrawler, _classify_listing
from services.research.models import BusinessQuery
from services.research.normalize import address_overlap, brand_tokens, same_site

DIRECTORY_ORIGINS = ("google_maps", "bing_maps")
GUESS_TLDS = (".com.tr", ".com", ".net", ".org")
MAX_GUESSES = 8
# Kişisel/genel amaçlı büyük siteler resmi site adayı olamaz (dizin, sosyal, haber, e-ticaret pazaryeri...)
REJECTED_HOST_PARTS = (
    "facebook.", "instagram.", "youtube.", "twitter.", "x.com", "linkedin.", "tiktok.", "pinterest.", "wikipedia.", "sahibinden.",
    "hepsiburada.", "trendyol.", "google.", "bing.", "yandex.", "tripadvisor.", "foursquare.", "yelp.", "firmarehberi", "yellowpages",
    "sirketler.", "cylex.", "hotfrog.", "n11.", "gittigidiyor.", "amazon.", "ebay.", "reddit.", "quora.", "wikimedia.",
)


@dataclass
class SiteCandidate:
    url: str
    origin: str  # google_maps | bing_maps | listing | domain_guess | arama
    verdict: str = "beklemede"  # dogrulandi | listelenmis | reddedildi | erisilemedi
    evidence: list[str] = field(default_factory=list)
    signals: WebsiteSignals | None = None
    extra_signals: list[WebsiteSignals] = field(default_factory=list)  # şube sayfası gibi ek sayfalar

    def to_dict(self) -> dict:
        return {"url": self.url, "origin": self.origin, "verdict": self.verdict, "evidence": self.evidence}

    @property
    def all_signals(self) -> list[WebsiteSignals]:
        return [s for s in [self.signals, *self.extra_signals] if s is not None and s.success]

    @property
    def phones(self) -> list[str]:
        out: list[str] = []
        for sig in self.all_signals:
            for number in sig.phones_found:
                if number not in out:
                    out.append(number)
        return out

    @property
    def emails(self) -> list[str]:
        out: list[str] = []
        for sig in self.all_signals:
            for email in sig.emails_found:
                if email not in out:
                    out.append(email)
        return out


def _brand_slugs(query: BusinessQuery) -> list[str]:
    tokens = brand_tokens(query.name, query.extra_generic)
    if not tokens:
        return []
    joined = "".join(tokens)
    slugs = [joined]
    if len(tokens) > 1:
        slugs.append("-".join(tokens))
    for word in ("isitme", "merkezi"):
        if any(word in fold(s) for s in query.sector_phrases):
            slugs.append(joined + word)
            break
    return [s for s in dict.fromkeys(slugs) if len(s) >= 4]


def _resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except socket.gaierror:
        return False


def domain_guesses(query: BusinessQuery) -> list[str]:
    """Marka adından alan adı adayları (sadece DNS'te var olanlar). Bunlar TAHMİNDİR: içerik doğrulaması şarttır."""
    urls: list[str] = []
    for slug in _brand_slugs(query):
        for tld in GUESS_TLDS:
            host = f"{slug}{tld}"
            if _resolves(host):
                urls.append(f"https://{host}/")
            if len(urls) >= MAX_GUESSES:
                return urls
    return urls


def verify_content(query: BusinessQuery, signals: WebsiteSignals, known_phones: list[str], known_address: str | None) -> tuple[bool, list[str]]:
    """Sitenin bu işletmeye ait olduğuna dair kanıtlar. Döndürür: (kabul, kanıt cümleleri)."""
    evidence: list[str] = []
    tokens = brand_tokens(query.name, query.extra_generic)
    schema = signals.schema_business or {}
    haystack = fold(" ".join(filter(None, [signals.title, signals.meta_description, " ".join(signals.h1_texts), schema.get("name"), (signals.text_excerpt or "")[:4000]])))
    haystack_tokens = set(haystack.split())

    brand_hit = bool(tokens) and any(t in haystack_tokens or (len(t) >= 5 and any(h.startswith(t) for h in haystack_tokens)) for t in tokens)
    # tire ile ayrılmış markalar ("si-ser" -> "siser") birleşik yazımla da aranır
    if not brand_hit and tokens and "".join(tokens) in haystack.replace(" ", ""):
        brand_hit = True
    if brand_hit:
        evidence.append("İşletme adı/markası sitede geçiyor")

    phone_hit = [p for p in known_phones if p in signals.phones_found]
    if phone_hit:
        evidence.append("Telefon numarası sitede de var")

    address_hit = None
    for source_text in (signals.address_text, schema.get("address")):
        overlap = address_overlap(known_address, source_text, exclude=query.extra_generic)
        if overlap is not None and overlap >= 0.5:
            address_hit = overlap
    if address_hit:
        evidence.append("Adres sitede de eşleşiyor")

    place_hit = any(fold(place) in haystack for place in query.place_names if len(place) > 3)
    if place_hit:
        evidence.append(f"Site metninde '{query.place}' geçiyor")

    accepted = bool(phone_hit) or bool(brand_hit and (address_hit or place_hit))
    return accepted, evidence


def evaluate_candidate(
    candidate: SiteCandidate, query: BusinessQuery, known_phones: list[str], known_address: str | None,
    crawler: RealWebsiteCrawler, extra_urls: list[str] | None = None,
) -> SiteCandidate:
    """Adayı hafif modda açar, içeriği işletmeyle karşılaştırır ve verdict'i belirler."""
    if _classify_listing(candidate.url) or any(part in (normalize_host(candidate.url) or "") for part in REJECTED_HOST_PARTS):
        candidate.verdict = "reddedildi"
        candidate.evidence.append("Kurumsal web sitesi değil (sosyal medya/dizin/pazaryeri adresi)")
        return candidate

    signals = crawler.analyze(candidate.url, light=True)
    candidate.signals = signals
    for extra in extra_urls or []:
        if same_site(extra, candidate.url) and extra.rstrip("/") != candidate.url.rstrip("/"):
            candidate.extra_signals.append(crawler.analyze(extra, light=True))

    if not signals.success:
        candidate.verdict = "erisilemedi"
        candidate.evidence.append(f"Site analiz edilemedi: {signals.error_reason}")
        return candidate

    accepted = False
    for sig in candidate.all_signals:
        ok, evidence = verify_content(query, sig, known_phones, known_address)
        for line in evidence:
            if line not in candidate.evidence:
                candidate.evidence.append(line)
        accepted = accepted or ok

    if accepted:
        candidate.verdict = "dogrulandi"
    elif candidate.origin in DIRECTORY_ORIGINS or candidate.origin == "listing":
        # Dizinde/kayıtta listelenmiş adres: içerik eşleşmese de reddedilmez ama "doğrulanmış" da sayılmaz
        candidate.verdict = "listelenmis"
        candidate.evidence.append("Sitede işletme adı/telefon/adres eşleşmesi bulunamadı (kayıtta listelenmiş adres)")
    else:
        candidate.verdict = "reddedildi"
        candidate.evidence.append("Site içeriği işletmeyle eşleşmedi — işletmeye bağlanmadı")
    return candidate


def find_official_site(
    query: BusinessQuery,
    known: list[tuple[str, str]],
    known_phones: list[str],
    known_address: str | None,
    *,
    crawler: RealWebsiteCrawler | None = None,
    extra_urls: list[str] | None = None,
    search_fn=None,
    allow_guess: bool = True,
) -> tuple[SiteCandidate | None, list[SiteCandidate], list[str]]:
    """Döndürür: (seçilen site | None, incelenen tüm adaylar, yöntem notları)."""
    crawler = crawler or RealWebsiteCrawler()
    notes: list[str] = []
    candidates: list[SiteCandidate] = []
    seen_hosts: set[str] = set()

    def add(url: str, origin: str) -> SiteCandidate | None:
        host = normalize_host(url)
        if not host or host in seen_hosts:
            return None
        seen_hosts.add(host)
        candidate = SiteCandidate(url=url, origin=origin)
        candidates.append(candidate)
        return candidate

    # 1-2) kayıtlarda/dizinlerde listelenen siteler
    for origin, url in known:
        candidate = add(url, origin)
        if candidate:
            evaluate_candidate(candidate, query, known_phones, known_address, crawler, extra_urls)

    def chosen() -> SiteCandidate | None:
        for verdict in ("dogrulandi", "listelenmis"):
            for candidate in candidates:
                if candidate.verdict == verdict:
                    return candidate
        return None

    if chosen():
        return chosen(), candidates, notes

    # 3) alan adı adayları
    if allow_guess:
        guesses = domain_guesses(query)
        notes.append(f"{len(guesses)} alan adı adayı DNS'te bulundu ve içerikle doğrulandı." if guesses else "Marka adından türetilen alan adı adaylarının hiçbiri mevcut değil.")
        for url in guesses:
            candidate = add(url, "domain_guess")
            if candidate:
                evaluate_candidate(candidate, query, known_phones, known_address, crawler)
                if candidate.verdict == "dogrulandi":
                    return candidate, candidates, notes

    # 4) web araması sonuçları (aday üretir; doğrulama şart)
    if search_fn is not None:
        hits = search_fn(f'"{query.name}" {query.place}')
        useful = [h for h in hits if not any(part in (normalize_host(h.url) or "") for part in REJECTED_HOST_PARTS)][:4]
        notes.append(f"Arama motoru {len(hits)} sonuç döndürdü, {len(useful)} kurumsal aday içerikle sınandı.")
        for hit in useful:
            candidate = add(hit.url, "arama")
            if candidate:
                evaluate_candidate(candidate, query, known_phones, known_address, crawler)
                if candidate.verdict == "dogrulandi":
                    return candidate, candidates, notes

    return None, candidates, notes
