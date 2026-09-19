"""Araştırma katmanının veri yapıları (kaynak durumları, dizin profilleri, alan kanıtları)."""

from dataclasses import dataclass, field
from datetime import datetime


# ------------------------------------------------------------------ kaynak durumu (arayüzde teknik olarak gösterilir)
SOURCE_CHECKED = "kontrol_edildi"  # kaynak açıldı ve okundu (sonuç bulunmuş ya da bulunmamış olabilir)
SOURCE_BLOCKED = "erisilemedi"  # kaynak otomatik erişimi engelledi / açılamadı
SOURCE_NO_MATCH = "eslesme_yok"  # kaynak açıldı ama bu işletmeyle güvenle eşleşen kayıt yok
SOURCE_SKIPPED = "atlandi"  # bu işletme için gerekmedi ya da başka kaynak yeterliydi

# ------------------------------------------------------------------ alan doğrulama durumu
VERIFIED = "dogrulandi"
CONFLICTING = "celiskili"
NOT_FOUND = "bulunamadi"
SINGLE_SOURCE = "tek_kaynak"  # değer var ama yalnızca güvenilir olmayan tek kaynakta (ör. yalnızca eski keşif kaydı)


@dataclass
class SourceStatus:
    key: str
    label: str
    status: str
    detail: str = ""
    checked_at: datetime | None = None

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "status": self.status, "detail": self.detail,
                "checked_at": self.checked_at.isoformat() if self.checked_at else None}


@dataclass
class BusinessQuery:
    """Araştırılacak işletmenin bilinen (OSM) verisi."""

    name: str
    place_names: list[str]  # [ilçe, il]
    lat: float | None
    lng: float | None
    phones: list[str] = field(default_factory=list)  # normalize
    address: str | None = None
    website: str | None = None
    email: str | None = None
    category: str | None = None
    google_url: str | None = None  # keşifte bulunan Google yer adresi (varsa doğrudan açılır, adla yeniden aranmaz)
    sector_phrases: list[str] = field(default_factory=list)
    extra_generic: set[str] = field(default_factory=set)  # eşleştirmede marka sayılmayacak sözcükler (yer/sektör adları)

    @property
    def place(self) -> str:
        return self.place_names[0] if self.place_names else ""

    @property
    def city(self) -> str:
        return self.place_names[-1] if self.place_names else ""


@dataclass
class MatchInfo:
    accepted: bool
    score: float
    signals: list[str] = field(default_factory=list)  # kullanıcıya gösterilen Türkçe kanıt cümleleri
    negatives: list[str] = field(default_factory=list)
    distance_m: int | None = None
    name_similarity: float = 0.0

    def to_dict(self) -> dict:
        return {"accepted": self.accepted, "score": self.score, "signals": self.signals, "negatives": self.negatives,
                "distance_m": self.distance_m, "name_similarity": self.name_similarity}


@dataclass
class MapsCandidate:
    name: str
    url: str
    lat: float | None = None
    lng: float | None = None
    rating: float | None = None
    review_count: int | None = None
    category: str | None = None
    address: str | None = None
    phone: str | None = None
    text: str = ""
    match: MatchInfo | None = None


@dataclass
class DirectoryProfile:
    """Bir harita dizininden (Google/Bing Haritalar) okunan işletme profili. Okunamayan alan None/boş kalır."""

    source: str  # google_maps | bing_maps
    name: str | None = None
    url: str | None = None
    place_id: str | None = None
    lat: float | None = None
    lng: float | None = None
    rating: float | None = None
    review_count: int | None = None
    category: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    hours_text: str | None = None
    hours: list[dict] = field(default_factory=list)  # [{"day": "Pazartesi", "hours": "09:00 - 18:30"}]
    description: str | None = None
    attributes: list[str] = field(default_factory=list)  # "Hakkında" sekmesindeki hizmet seçenekleri vb.
    about_text: str | None = None
    plus_code: str | None = None
    extra_links: list[str] = field(default_factory=list)  # profildeki ek bağlantılar (ör. şube sayfası, randevu/menü)
    cover_photo_date: str | None = None  # "Eki 2023" (yalnızca kapak fotoğrafının tarihi)
    reviews: list[dict] = field(default_factory=list)  # [{"relative": "5 ay önce", "has_owner_reply": True, "author": ...}]
    reviews_sort: str | None = None
    last_review_relative: str | None = None
    last_review_at: datetime | None = None  # YAKLAŞIK (Google göreli tarih verir)
    owner_replies: int | None = None
    reviews_sampled: int = 0
    match: MatchInfo | None = None

    def to_dict(self) -> dict:
        data = {k: v for k, v in self.__dict__.items() if k not in ("match", "last_review_at")}
        data["last_review_at"] = self.last_review_at.isoformat() if self.last_review_at else None
        data["match"] = self.match.to_dict() if self.match else None
        return data
