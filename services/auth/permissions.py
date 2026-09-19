"""Roller ve izinler — TEK yerde. Yetki kontrolü API tarafında (apps/api/deps.py) bu tablo ile yapılır; arayüz yalnızca aynı tabloyu
menüyü gizlemek için kullanır, güvenlik sınırı değildir.

Roller: Yönetici (yonetici) · Çalışan (calisan) · Stajyer (stajyer)
"""

YONETICI, CALISAN, STAJYER = "yonetici", "calisan", "stajyer"
ROLES = (YONETICI, CALISAN, STAJYER)
ROLE_LABELS = {YONETICI: "Yönetici", CALISAN: "Çalışan", STAJYER: "Stajyer"}
ROLE_ICONS = {YONETICI: "👑", CALISAN: "👨‍💼", STAJYER: "🎓"}

_ALL = frozenset(ROLES)
_STAFF = frozenset({YONETICI, CALISAN})
_ADMIN = frozenset({YONETICI})

# izin → izinli roller
PERMISSIONS: dict[str, frozenset[str]] = {
    # ---- tüm roller (satış operasyonu)
    "search": _ALL,            # şehir/ilçe/sektör ile firma arama (keşif)
    "analyze": _ALL,           # firma analizi başlatma
    "view_business": _ALL,     # firma detayı, analiz sonuçları, satış fırsatları, skor
    "crm_use": _ALL,           # CRM'e ekleme, durum güncelleme, CRM notu
    "guides": _ALL,            # çözüm rehberi
    "dashboard": _ALL,         # bugünün potansiyel müşterileri, analiz sayaçları
    # ---- yönetici + çalışan
    "sales_note": _STAFF,      # satış notu oluşturma
    "export": _STAFF,          # Excel/CSV dışa aktarma
    "crm_assign": _STAFF,      # CRM kaydının sorumlu personelini değiştirme
    "sales_reports": _STAFF,   # satış hunisi, hizmet/sektör bazlı gelir raporu
    # ---- yalnızca yönetici
    "users_manage": _ADMIN,    # kullanıcı oluştur/düzenle/pasifleştir/rol/şifre sıfırla
    "activity_view_all": _ADMIN,  # tüm personel aktiviteleri
    "staff_reports": _ADMIN,   # personel bazlı raporlar
    "api_settings": _ADMIN,    # sistem/API ayarları
    "pricing_manage": _ADMIN,  # Hizmet ve Fiyat Ayarları
    "email_settings": _ADMIN,  # E-posta (SMTP) ayarları
}


def can(role: str | None, permission: str) -> bool:
    return bool(role) and role in PERMISSIONS.get(permission, frozenset())


def permissions_for(role: str | None) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)
