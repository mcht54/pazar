"""Sosyal medya hesabı bulma: yalnızca İŞLETMEYE AİT olduğu doğrulanabilen hesaplar eklenir.

Kaynaklar (güvenilirlik sırasıyla): (1) doğrulanmış resmi web sitesinde bağlantılı hesap, (2) sitede bağlantılı ama site içeriği
işletmeyle eşleşmemiş/yalnızca dizinde listeli, (3) keşif kaydı. Arama motorlarıyla bulunan ya da alan adından tahmin edilen
hesaplar EKLENMEZ (bu ortamda aramalar güvenilir değil ve tahmin, yanlış hesaba bağlama riski taşır).
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from services.research.models import NOT_FOUND, SINGLE_SOURCE, VERIFIED

NETWORKS = (
    ("instagram", "Instagram", "instagram.com"),
    ("facebook", "Facebook", "facebook.com"),
    ("linkedin", "LinkedIn", "linkedin.com"),
    ("youtube", "YouTube", "youtube.com"),
)
_NON_PROFILE_PATHS = ("sharer", "share", "intent", "login", "dialog", "plugins", "tr/", "p/", "reel", "explore", "watch", "embed", "hashtag", "policies", "help")


@dataclass
class SocialFinding:
    network: str
    label: str
    url: str | None
    status: str
    sources: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {"network": self.network, "label": self.label, "url": self.url, "status": self.status, "sources": self.sources, "note": self.note}


def clean_profile_url(url: str | None, domain: str) -> str | None:
    """Profil adresini sadeleştirir (parametreler/parça atılır). Paylaşım/gömme gibi profil olmayan adresler None döner."""
    if not url:
        return None
    if not re.match(r"^https?://", url):
        url = "https://" + url.lstrip("/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("tr-tr.")
    if host != domain and not host.endswith("." + domain):
        return None
    path = parsed.path.strip("/")
    if not path or any(path.lower().startswith(p) for p in _NON_PROFILE_PATHS):
        return None
    return f"https://www.{domain}/{path}"


def collect_social(listing_social: dict, site_signals: list, site_verdict: str | None) -> list[SocialFinding]:
    """Döndürür: her ağ için bir SocialFinding (bulunamayanlar NOT_FOUND)."""
    findings: list[SocialFinding] = []
    for network, label, domain in NETWORKS:
        site_url = None
        for signals in site_signals:
            candidate = clean_profile_url((signals.social_links or {}).get(network), domain)
            if candidate:
                site_url = candidate
                break
        listing_url = clean_profile_url((listing_social or {}).get(network), domain)

        if site_url and site_verdict == "dogrulandi":
            sources = ["Resmi web sitesi"] + (["Keşif kaydı"] if listing_url and listing_url.lower() == site_url.lower() else [])
            findings.append(SocialFinding(network, label, site_url, VERIFIED, sources,
                                          "Doğrulanmış resmi web sitesinde bağlantılı (marka/kurum hesabı olabilir)."))
        elif site_url:
            findings.append(SocialFinding(network, label, site_url, SINGLE_SOURCE, ["Web sitesi (içerik işletmeyle eşleşmedi)"],
                                          "Web sitesinde bağlantılı ama site işletmeyle tam doğrulanamadığı için hesap doğrulanmadı."))
        elif listing_url:
            findings.append(SocialFinding(network, label, listing_url, SINGLE_SOURCE, ["Keşif kaydı"],
                                          "Yalnızca keşif kaydında var; başka kaynakla doğrulanamadı."))
        else:
            findings.append(SocialFinding(network, label, None, NOT_FOUND, [],
                                          "Resmi web sitesinde ve kayıtlarda bağlantı bulunamadı."))
    return findings
