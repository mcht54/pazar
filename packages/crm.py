"""CRM satış aşamaları (9 aşama) — TÜM sistemde (API doğrulaması, rapor, arayüz, testler) bu adlar kullanılır.

- Bir firmanın CRM'de olması `businesses.crm_added_at` doluluğuyla ifade edilir (analiz firmayı CRM'e OTOMATİK EKLEMEZ).
- Güncel durum: businesses.crm_stage · not: businesses.staff_note · son işlem: businesses.crm_updated_at · geçmiş: crm_activities.
- Eski adlar API'de KABUL EDİLMEZ; veritabanında kalmış eski kayıtlar migration ile (ve API açılışında) yeni adlara taşınır.
"""

# Arayüzde gösterim sırası
CRM_STAGES = [
    "Yeni",
    "Aranacak",
    "Daha Sonra Ara",
    "Arandı",
    "Görüşüldü",
    "Teklif Gönderildi",
    "Takip Bekliyor",
    "Kazanıldı",
    "Kaybedildi",
]
# YALNIZCA veritabanında saklı kalmış eski adları düzeltmek için (eski süreçlerin yazdığı kayıtlar; bkz. crm_service.normalize_legacy_stages).
# API doğrulaması bu tabloyu KULLANMAZ: eski adlar (Teklif Verildi, Takipte, Müşteri Oldu, Olumsuz …) istekte REDDEDİLİR.
LEGACY_STAGE_ALIASES = {
    "Teklif Verildi": "Teklif Gönderildi",
    "Takipte": "Takip Bekliyor",
    "Müşteri Oldu": "Kazanıldı",
    "Olumsuz": "Kaybedildi",
    # ara sürümlerde kullanılmış adlar
    "Yeni Lead": "Yeni",
    "Yeni Potansiyel": "Yeni",
    "İletişime Geçildi": "Arandı",
    "Ulaşılamadı": "Arandı",
    "İlgileniyor": "Görüşüldü",
    "Teklif Hazırlanıyor": "Teklif Gönderildi",
}
DEFAULT_STAGE = "Yeni"  # CRM'e eklenmemiş firmaların dahili varsayılanı (CRM'de sayılmaz)
ADD_DEFAULT_STAGE = "Aranacak"  # "CRM'e Ekle" penceresinde önerilen ilk durum
# "Bugün kimi aramalıyım?" eski panelinde yer alabilecek durumlar (henüz kapanmamış/aranacak işletmeler)
CALLABLE_STAGES = ["Yeni", "Aranacak", "Daha Sonra Ara", "Takip Bekliyor"]
# CRM ekranında "durum" sıralaması: önce çalışılması gerekenler
WORK_ORDER = ["Aranacak", "Daha Sonra Ara", "Takip Bekliyor", "Yeni", "Arandı", "Görüşüldü", "Teklif Gönderildi", "Kazanıldı", "Kaybedildi"]

# Satış hunisi: bir firma, geçmişinde ulaştığı EN İLERİ aşamaya göre sayılır ("o aşamaya veya sonrasına ulaştı").
FUNNEL_RANK = {"Arandı": 1, "Görüşüldü": 2, "Teklif Gönderildi": 3, "Kazanıldı": 4}
FUNNEL_STEPS = ["Arandı", "Görüşme", "Teklif", "Kazanıldı"]  # FUNNEL_RANK değerleri 1..4 ("Teklif" = teklif GÖNDERİLDİ)
CLOSED_STAGES = ["Kazanıldı", "Kaybedildi"]
OPEN_STAGES = [s for s in CRM_STAGES if s not in CLOSED_STAGES]
OFFER_STAGES = ("Teklif Gönderildi",)
WON_STAGE = "Kazanıldı"
LOST_STAGE = "Kaybedildi"
# Bu aşamalara geçiş = gerçek bir iletişim/ilerleme (son görüşme tarihi güncellenir)
CONTACT_STAGES = ("Arandı", "Görüşüldü", "Teklif Gönderildi")

# İletişim kaydı (arama/mesaj/görüşme) — aşama DEĞİL, geçmişte tutulan olay
CONTACT_CHANNELS = {"arama": "Arama", "whatsapp": "WhatsApp", "eposta": "E-posta", "yuz_yuze": "Yüz yüze"}
CONTACT_RESULTS = ["Ulaşılamadı", "Görüşüldü", "İlgileniyor", "Teklif istendi", "İlgilenmiyor", "Daha sonra aranacak"]

LOST_REASONS = ["Bütçe uygun değil", "Rakip ile çalışıyor", "İhtiyaç duymuyor", "Karar vericiye ulaşılamadı", "Zamanlama uygun değil", "Fiyatı yüksek buldu", "Diğer"]


def normalize_stage(stage: str | None) -> str | None:
    """STRICT doğrulama: yalnızca CRM_STAGES içindeki adlar geçerlidir (boşluklar kırpılır). Eski adlar (Teklif Verildi, Takipte, …) geçersizdir → None."""
    if stage is None:
        return None
    stage = stage.strip()
    return stage if stage in CRM_STAGES else None
