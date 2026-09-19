"""Sektör profilleri: bir sektörde hangi dijital/fiziksel ihtiyaçların anlamlı olduğunu tanımlar.

Bu profil TESPİT değildir, sektörün doğası hakkında bir bağlamdır: ör. ürün satan bir sektörde
"sitede sepet yok" bir eksiktir, ama bir hukuk bürosunda değildir. Kanıt gerektirmeyen (doğrulanamayan)
hizmet önerileri yalnızca "olası ihtiyaç — doğrulama gerekir" olarak, seviyeyi etkilemeden gösterilir.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SectorProfile:
    sells_products: bool = False  # e-ticaret ilgili mi
    storefront: bool = False  # fiziksel mekân/tabela/branda ilgili mi
    appointment_based: bool = False  # randevu ile çalışıyor mu
    reservation_based: bool = False  # rezervasyon ile çalışıyor mu
    booking_important: bool = True  # online randevu/rezervasyon eksikliği ciddi bir eksik mi (restoranlarda telefonla rezervasyon yaygın → False)
    local_intent: bool = True  # "yakınımdaki X" aramaları yüksek mi (SEO/Ads/GBP ilgili)
    print_need: str = "kartvizit ve tanıtım broşürü"
    customer_noun: str = "müşteri"
    action_word: str = "iletişim"
    google_types: frozenset[str] = field(default_factory=frozenset)


_GROUP_PROFILES: dict[str, SectorProfile] = {
    "Sağlık ve Tıp": SectorProfile(storefront=True, appointment_based=True, print_need="kartvizit, bilgilendirme broşürü ve randevu kartı", customer_noun="hasta", action_word="randevu"),
    "Güzellik ve Kişisel Bakım": SectorProfile(storefront=True, appointment_based=True, print_need="kartvizit, fiyat/hizmet listesi ve kampanya broşürü", action_word="randevu"),
    "Yeme-İçme": SectorProfile(storefront=True, reservation_based=True, booking_important=False, print_need="menü, kartvizit ve masa üstü baskılar", customer_noun="misafir", action_word="rezervasyon"),
    "Konaklama ve Turizm": SectorProfile(storefront=True, reservation_based=True, print_need="broşür, oda içi baskılar ve kartvizit", customer_noun="misafir", action_word="rezervasyon"),
    "Otomotiv": SectorProfile(storefront=True, appointment_based=True, print_need="kartvizit, servis/kampanya broşürü", action_word="randevu"),
    "Emlak, İnşaat ve Yapı": SectorProfile(storefront=True, print_need="katalog, proje broşürü ve kartvizit", action_word="teklif"),
    "Ev, Mobilya ve Dekorasyon": SectorProfile(sells_products=True, storefront=True, print_need="katalog, broşür ve kartvizit", action_word="sipariş"),
    "Perakende ve Mağazacılık": SectorProfile(sells_products=True, storefront=True, print_need="poşet, etiket, afiş ve kartvizit", action_word="sipariş"),
    "Profesyonel Hizmetler": SectorProfile(storefront=True, appointment_based=True, print_need="kurumsal kartvizit, kurumsal dosya ve broşür", action_word="randevu"),
    "Reklam, Yazılım ve Medya": SectorProfile(storefront=False, local_intent=False, print_need="kartvizit ve portföy dosyası", action_word="teklif"),
    "Eğitim": SectorProfile(storefront=True, print_need="tanıtım broşürü, afiş ve kayıt formları", customer_noun="öğrenci/veli", action_word="kayıt"),
    "Spor, Etkinlik ve Eğlence": SectorProfile(storefront=True, print_need="afiş, üyelik kartı ve broşür", action_word="üyelik"),
    "Ulaşım ve Lojistik": SectorProfile(storefront=False, print_need="kartvizit ve araç giydirme", action_word="teklif"),
    "Sanayi, Toptan ve Tarım": SectorProfile(storefront=False, local_intent=False, print_need="katalog, kurumsal dosya ve kartvizit", action_word="teklif"),
    "Kişisel Hizmetler ve Tamir": SectorProfile(storefront=True, print_need="kartvizit ve hizmet broşürü", action_word="randevu"),
}

_DEFAULT = SectorProfile()

# Google Places birincil türü bu sektör için beklenen türlerden biri mi? (GBP "kategori doğru mu" kontrolü)
_GOOGLE_TYPES: dict[str, frozenset[str]] = {
    "Diş Kliniği": frozenset({"dentist", "dental_clinic"}),
    "Özel Klinik / Poliklinik": frozenset({"medical_clinic", "doctor", "hospital", "health", "physiotherapist"}),
    "Doktor Muayenehanesi": frozenset({"doctor", "medical_clinic", "medical_lab"}),
    "Özel Hastane": frozenset({"hospital"}),
    "Eczane": frozenset({"pharmacy", "drugstore"}),
    "Optik / Gözlükçü": frozenset({"optician", "store"}),
    "İşitme Cihazı Merkezi": frozenset({"hearing_aid_store", "audiologist", "medical_clinic", "doctor", "health", "store", "medical_supply_store"}),
    "Fizik Tedavi ve Rehabilitasyon": frozenset({"physiotherapist", "medical_clinic"}),
    "Veteriner": frozenset({"veterinary_care"}),
    "Güzellik Salonu": frozenset({"beauty_salon", "hair_care", "spa", "nail_salon"}),
    "Kuaför / Berber": frozenset({"hair_salon", "hair_care", "barber_shop", "beauty_salon"}),
    "Restoran": frozenset({"restaurant", "meal_takeaway", "meal_delivery", "food"}),
    "Kafe": frozenset({"cafe", "coffee_shop", "bakery", "restaurant"}),
    "Fırın": frozenset({"bakery"}),
    "Pastane ve Tatlıcı": frozenset({"bakery", "dessert_shop", "confectionery", "cafe"}),
    "Otel": frozenset({"hotel", "lodging", "resort_hotel"}),
    "Emlak Ofisi": frozenset({"real_estate_agency"}),
    "Hukuk Bürosu": frozenset({"lawyer", "attorney"}),
    "Muhasebe ve Mali Müşavirlik": frozenset({"accounting", "accountant"}),
    "Sigorta Acentesi": frozenset({"insurance_agency"}),
    "Oto Galeri": frozenset({"car_dealer", "used_car_dealer"}),
    "Oto Servis ve Tamir": frozenset({"car_repair", "auto_repair_shop"}),
    "Oto Yıkama": frozenset({"car_wash"}),
    "Spor Salonu": frozenset({"gym", "fitness_center", "sports_club"}),
    "Çiçekçi": frozenset({"florist"}),
    "Kırtasiye": frozenset({"book_store", "store"}),
    "Reklam Ajansı": frozenset({"advertising_agency", "marketing_agency", "corporate_office"}),
    "Web Tasarım ve Yazılım": frozenset({"software_company", "corporate_office", "web_designer"}),
    "Matbaa ve Baskı": frozenset({"printing_service", "print_shop", "store"}),
}


def get_sector_profile(sector_name: str, group_name: str | None) -> SectorProfile:
    base = _GROUP_PROFILES.get(group_name or "", _DEFAULT)
    types = _GOOGLE_TYPES.get(sector_name)
    if types is None:
        return base
    return SectorProfile(**{**base.__dict__, "google_types": types})
