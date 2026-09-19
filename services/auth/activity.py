"""Personel aktivite kaydı: her önemli işlem kullanıcıyla ilişkilendirilerek `activity_log` tablosuna yazılır (yalnızca eklenir)."""

from sqlalchemy.orm import Session

from packages.db.models import ActivityLog, User

# eylem anahtarı → Türkçe etiket (arayüzde ve raporlarda gösterilir)
ACTIONS: dict[str, str] = {
    "login": "Giriş yaptı",
    "login_failed": "Başarısız giriş denemesi",
    "logout": "Çıkış yaptı",
    "search": "Firma araması yaptı",
    "analyze": "Firma analizi başlattı",
    "crm_add": "CRM'e ekledi",
    "crm_status": "CRM durumunu değiştirdi",
    "crm_note": "CRM notu ekledi/düzenledi",
    "crm_contact": "İletişim kaydı ekledi",
    "crm_update": "Satış bilgilerini güncelledi",
    "crm_follow_up": "Takip planladı/kaldırdı",
    "crm_follow_up_done": "Takibi tamamladı",
    "offer": "Teklif gönderdi",
    "customer_won": "Satışı kazandı",
    "password_forgot": "Şifremi unuttum talebi",
    "password_set": "Şifre bağlantısıyla şifre belirledi",
    "invite_sent": "Şifre belirleme bağlantısı gönderdi",
    "email_settings_update": "E-posta ayarlarını güncelledi",
    "email_test": "E-posta bağlantısını test etti",
    "price_update": "Hizmet fiyatını güncelledi",
    "export": "Dışa aktardı",
    "sales_note": "Satış notu oluşturdu",
    "user_create": "Kullanıcı oluşturdu",
    "user_update": "Kullanıcıyı düzenledi",
    "user_deactivate": "Kullanıcıyı pasifleştirdi",
    "user_activate": "Kullanıcıyı aktifleştirdi",
    "role_change": "Kullanıcı rolünü değiştirdi",
    "password_reset": "Kullanıcı şifresini sıfırladı",
    "password_change": "Kendi şifresini değiştirdi",
    "api_settings_update": "API ayarlarını güncelledi",
    "api_test": "API bağlantısını test etti",
    "api_toggle": "API durumunu değiştirdi",
}


def log_activity(
    db: Session, user: User | None, action: str, *, business_id: int | None = None, detail: str | None = None,
    meta: dict | None = None, ip: str | None = None, commit: bool = False,
) -> ActivityLog:
    entry = ActivityLog(user_id=user.id if user else None, action=action, business_id=business_id, detail=detail, meta=meta, ip=ip)
    db.add(entry)
    if commit:
        db.commit()
    return entry
