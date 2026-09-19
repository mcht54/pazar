"""CRM işlemleri: firmayı CRM'e ekleme, durum/not güncelleme ve işlem geçmişi.

İlkeler:
- CRM'de olmak `Business.crm_added_at` doluluğudur. Analiz, keşif ya da yeniden analiz bunu ASLA doldurmaz ve mevcut CRM kaydını/geçmişini silmez.
- Her CRM işlemi `crm_activities` tablosuna zaman damgalı (gerçek `created_at`) ve KULLANICILI bir kayıt yazar; ayrıca personel aktivite
  günlüğüne (activity_log) işlenir. `Business.crm_updated_at/by/last_action` = son işlem (kim, ne zaman, ne).
- Geçmiş kayıtları silinmez/düzenlenmez (yalnızca eklenir). Kullanıcısı bilinmeyen eski kayıtlar "Bilinmiyor (eski kayıt)" gösterilir — uydurulmaz.
"""

from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from packages.crm import CONTACT_CHANNELS, CONTACT_RESULTS, CONTACT_STAGES, CRM_STAGES, DEFAULT_STAGE, LOST_STAGE, WON_STAGE, normalize_stage
from packages.db.models import Business, CrmActivity, User
from services import follow_up_service as fus
from services.auth.activity import log_activity

TZ = ZoneInfo("Europe/Istanbul")
MAX_AMOUNT = Decimal("999999999.99")

NOTE_LIMIT = 4000
UNKNOWN_USER = "Bilinmiyor (eski kayıt)"


class CrmError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def in_crm(business: Business) -> bool:
    return business.crm_added_at is not None


def _validate_stage(stage: str) -> str:
    """Eski durum adlarını yeni ada çevirir (Takipte → Takip Bekliyor …); geçersizse 422."""
    normalized = normalize_stage(stage)
    if normalized is None:
        raise CrmError(422, f"Geçersiz CRM durumu. Geçerli durumlar: {', '.join(CRM_STAGES)}")
    return normalized


def parse_amount(value, label: str) -> Decimal | None:
    """Tutar (TL): boş → None; negatif/sayı olmayan → 422. Uydurma/otomatik tutar yazılmaz."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        amount = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        raise CrmError(422, f"{label} geçerli bir sayı olmalı.") from None
    if not amount.is_finite() or amount < 0 or amount > MAX_AMOUNT:
        raise CrmError(422, f"{label} 0 ile {MAX_AMOUNT:,.0f} arasında olmalı.")
    return amount.quantize(Decimal("0.01"))


def parse_follow_up(value) -> datetime | None:
    """Takip tarihi: 'YYYY-MM-DD' (Europe/Istanbul 00:00) ya da tam ISO tarih-saat. Boş → None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=TZ)
    text = str(value).strip()
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), time(0, 0), tzinfo=TZ)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise CrmError(422, "Takip tarihi geçerli bir tarih olmalı (GG.AA.YYYY veya YYYY-AA-GG).") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)


def follow_up_state(business: Business, now: datetime | None = None) -> str | None:
    """Takip durumu (Europe/Istanbul takvim günü): overdue (gecikmiş) | today (bugün) | upcoming (ileri tarihli) | None (takip yok)."""
    if business.next_follow_up_at is None or business.crm_added_at is None:
        return None
    today = (now or datetime.now(timezone.utc)).astimezone(TZ).date()
    due = business.next_follow_up_at.astimezone(TZ).date()
    return "overdue" if due < today else "today" if due == today else "upcoming"


def _clean_note(note: str | None) -> str:
    return (note or "").strip()[:NOTE_LIMIT]


def _milestone_logs(db: Session, user: User | None, business: Business, stage: str, ip: str | None) -> None:
    """Teklif verildi / Müşteri oldu gibi satış kilometre taşları ayrıca aktivite kaydına işlenir (personel raporları için)."""
    if stage == "Teklif Gönderildi":
        log_activity(db, user, "offer", business_id=business.id, detail=f"{business.name}: Teklif Gönderildi", ip=ip)
    elif stage == WON_STAGE:
        log_activity(db, user, "customer_won", business_id=business.id, detail=f"{business.name}: Kazanıldı", ip=ip)


FIELD_KEYS = ("follow_up_at", "follow_up_note", "offer_amount", "sale_amount", "lost_reason", "interested_service", "owner_id")
FOLLOW_UP_RESULTS = ["Görüşüldü", "Ulaşılamadı", "Tekrar takip edilecek", "Karar bekleniyor", "İlgilenmiyor"]


def _apply_fields(db: Session, business: Business, stage: str, fields: dict, now: datetime, actor: User | None = None) -> dict:
    """Satış takibi alanlarını doğrulayıp uygular; gerçekten DEĞİŞENLERİ {alan: yeni değer} olarak döndürür (aktivite `meta` için)."""
    changed: dict = {}

    def put(attr: str, value, key: str | None = None):
        if getattr(business, attr) != value:
            setattr(business, attr, value)
            changed[key or attr] = value.isoformat() if isinstance(value, datetime) else float(value) if isinstance(value, Decimal) else value

    if "interested_service" in fields:
        put("interested_service", ((fields["interested_service"] or "").strip()[:120]) or None)
    if "offer_amount" in fields:
        put("offer_amount", parse_amount(fields["offer_amount"], "Teklif tutarı"))
    if "sale_amount" in fields:
        amount = parse_amount(fields["sale_amount"], "Satış tutarı")
        if amount is not None and stage != WON_STAGE:
            raise CrmError(422, "Satış tutarı yalnızca 'Kazanıldı' durumunda girilir.")
        put("sale_amount", amount)
    if "lost_reason" in fields:
        reason = ((fields["lost_reason"] or "").strip()[:300]) or None
        if reason is not None and stage != LOST_STAGE:
            raise CrmError(422, "Kaybedilme nedeni yalnızca 'Kaybedildi' durumunda girilir.")
        put("lost_reason", reason)
    if "follow_up_note" in fields:
        put("follow_up_note", ((fields["follow_up_note"] or "").strip()[:1000]) or None)
    if "follow_up_at" in fields:
        when = parse_follow_up(fields["follow_up_at"])
        if when is not None and stage in (WON_STAGE, LOST_STAGE):
            raise CrmError(422, "Kapanmış (Kazanıldı/Kaybedildi) kayıtlar için takip tarihi girilemez.")
        put("next_follow_up_at", when, "follow_up_at")
        if when is None:
            put("follow_up_note", None)
    if "follow_up_at" in fields or "follow_up_note" in fields:
        # takipler `follow_ups` tablosunda tutulur; bu alan en yakın bekleyen takibi günceller/oluşturur/kaldırır
        fus.set_primary(db, business, fields.get("follow_up_at"), note=fields.get("follow_up_note"), note_provided="follow_up_note" in fields,
                        due_provided="follow_up_at" in fields, actor=actor)
    if "owner_id" in fields:
        owner_id = fields["owner_id"]
        if owner_id is not None:
            owner = db.get(User, owner_id)
            if owner is None or not owner.is_active:
                raise CrmError(422, "Sorumlu personel bulunamadı veya pasif.")
        put("crm_owner_id", owner_id, "owner_id")
    return changed


def _stage_side_effects(db: Session, business: Business, old: str | None, stage: str, now: datetime, fields: dict, changed: dict) -> None:
    """Durum değişince tutarlılık: kapanışta takip temizlenir, aşamadan çıkılınca o aşamaya ait tutar/neden temizlenir, görüşme tarihi güncellenir."""
    if stage in CONTACT_STAGES:
        business.last_contact_at = now
    if stage in (WON_STAGE, LOST_STAGE) and (business.next_follow_up_at is not None or fus.pending_for(db, business.id)):
        fus.cancel_all_pending(db, business, "Firma kapandı")  # bekleyen takipler İPTAL edilir (silinmez)
        changed["follow_up_at"] = None
    if old == WON_STAGE and stage != WON_STAGE and "sale_amount" not in fields and business.sale_amount is not None:
        business.sale_amount = None
        changed["sale_amount"] = None
    if old == LOST_STAGE and stage != LOST_STAGE and "lost_reason" not in fields and business.lost_reason is not None:
        business.lost_reason = None
        changed["lost_reason"] = None


def add_to_crm(db: Session, business: Business, stage: str, note: str | None = None, *, user: User | None = None, ip: str | None = None, fields: dict | None = None) -> None:
    """Firmayı CRM'e alır (yalnızca CRM'de değilse). Durum + (varsa) not tek bir 'added' kaydı olarak geçmişe yazılır."""
    stage = _validate_stage(stage)
    if in_crm(business):
        raise CrmError(409, "Bu firma zaten CRM'de. Durumunu CRM bilgilerinden değiştirebilirsiniz.")
    fields = {k: v for k, v in (fields or {}).items() if k in FIELD_KEYS}
    now = datetime.now(timezone.utc)
    text = _clean_note(note)
    business.crm_stage = stage
    business.crm_added_at = now
    business.crm_updated_at = now
    business.crm_added_by = business.crm_updated_by = user.id if user else None
    if "owner_id" not in fields:
        business.crm_owner_id = user.id if user else None
    business.crm_last_action = f"CRM'e eklendi ({stage})"
    if text:
        business.staff_note = text
    changed = _apply_fields(db, business, stage, fields, now, user)
    _stage_side_effects(db, business, None, stage, now, fields, changed)
    db.add(CrmActivity(business_id=business.id, type="added", from_stage=None, to_stage=stage, note=text or None, meta=changed or None,
                       created_by=user.name if user else "personel", user_id=user.id if user else None, created_at=now))
    log_activity(db, user, "crm_add", business_id=business.id, detail=f"{business.name}: CRM'e eklendi ({stage})", ip=ip)
    _milestone_logs(db, user, business, stage, ip)
    db.commit()


def update_crm(db: Session, business: Business, stage: str | None, note: str | None, *, user: User | None = None, ip: str | None = None, fields: dict | None = None) -> bool:
    """Durum, CRM notu ve satış takibi alanlarını (takip tarihi, teklif/satış tutarı, kayıp nedeni, hizmet, sorumlu) günceller.

    CRM'de olmayan firmada bu, açık bir CRM işlemi sayılır ve firmayı CRM'e ekler.
    Döndürür: gerçekten bir değişiklik yapıldı mı (değişiklik yoksa zaman damgası/geçmiş değişmez).
    """
    stage = _validate_stage(stage) if stage is not None else None
    fields = {k: v for k, v in (fields or {}).items() if k in FIELD_KEYS}
    if not in_crm(business):
        add_to_crm(db, business, stage or business.crm_stage or DEFAULT_STAGE, note, user=user, ip=ip, fields=fields)
        return True
    now = datetime.now(timezone.utc)
    target = stage or business.crm_stage
    stage_changed = stage is not None and stage != business.crm_stage
    text = _clean_note(note) if note is not None else None
    note_changed = text is not None and text != (business.staff_note or "")
    changed = _apply_fields(db, business, target, fields, now, user)
    if stage_changed:
        _stage_side_effects(db, business, business.crm_stage, target, now, fields, changed)
    if not stage_changed and not note_changed and not changed:
        return False
    uid, uname = (user.id if user else None), (user.name if user else "personel")
    if stage_changed:
        old = business.crm_stage
        db.add(CrmActivity(business_id=business.id, type="status_change", from_stage=old, to_stage=stage,
                           note=(text or None) if note_changed else None, meta=changed or None, created_by=uname, user_id=uid, created_at=now))
        business.crm_stage = stage
        business.crm_last_action = f"{old} → {stage}"
        log_activity(db, user, "crm_status", business_id=business.id, detail=f"{business.name}: {old} → {stage}", ip=ip)
        _milestone_logs(db, user, business, stage, ip)
    elif note_changed:
        db.add(CrmActivity(business_id=business.id, type="note", from_stage=None, to_stage=business.crm_stage,
                           note=text or "(not silindi)", meta=changed or None, created_by=uname, user_id=uid, created_at=now))
        business.crm_last_action = "CRM notu güncellendi"
    else:
        kind = "follow_up" if set(changed) <= {"follow_up_at", "follow_up_note"} else "sales_update"
        label = "Takip planlandı" if kind == "follow_up" and changed.get("follow_up_at") else "Takip kaldırıldı" if kind == "follow_up" else "Satış bilgileri güncellendi"
        db.add(CrmActivity(business_id=business.id, type=kind, from_stage=None, to_stage=business.crm_stage, note=label, meta=changed,
                           created_by=uname, user_id=uid, created_at=now))
        business.crm_last_action = label
        log_activity(db, user, "crm_follow_up" if kind == "follow_up" else "crm_update", business_id=business.id, detail=f"{business.name}: {label}", ip=ip)
    if note_changed:
        business.staff_note = text or None
        log_activity(db, user, "crm_note", business_id=business.id, detail=f"{business.name}: CRM notu " + ("güncellendi" if text else "silindi"), ip=ip)
    business.crm_updated_at = now
    business.crm_updated_by = uid
    db.commit()
    return True


def complete_follow_up(db: Session, business: Business, result: str, note: str | None, next_at, *, user: User | None = None, ip: str | None = None) -> None:
    """En yakın bekleyen takibi tamamlar: sonuç + not geçmişe yazılır; istenirse yeni takip tarihi verilir (yoksa takip kapanır)."""
    if not in_crm(business):
        raise CrmError(409, "Firma CRM'de değil.")
    pending = fus.pending_for(db, business.id)
    if not pending:
        raise CrmError(409, "Bu firmada açık bir takip yok.")
    complete_follow_up_row(db, business, pending[0], result, note, next_at, user=user, ip=ip)


def complete_follow_up_row(db: Session, business: Business, fu, result: str, note: str | None, next_at, *, user: User | None = None, ip: str | None = None) -> None:
    """Belirli bir takibi tamamlar (takip kimliğiyle): sonuç + not, isteğe bağlı yeni takip; CRM geçmişine ve aktivite günlüğüne işlenir."""
    if fu.status != fus.PENDING:
        raise CrmError(409, "Bu takip zaten kapatılmış.")
    if result not in FOLLOW_UP_RESULTS:
        raise CrmError(422, f"Geçersiz takip sonucu. Geçerli sonuçlar: {', '.join(FOLLOW_UP_RESULTS)}")
    upcoming = parse_follow_up(next_at)
    if business.crm_stage in (WON_STAGE, LOST_STAGE) and upcoming is not None:
        raise CrmError(422, "Kapanmış kayıtlar için yeni takip tarihi girilemez.")
    now = datetime.now(timezone.utc)
    due = fu.due_at
    text = _clean_note(note)
    fus.complete(db, fu, result, text or None, user)
    if upcoming is not None:
        fus.create(db, business, next_at, None, owner_id=fu.user_id, actor=user)
    meta = {"result": result, "due_at": due.isoformat(), "follow_up_id": fu.id, "next_follow_up_at": upcoming.isoformat() if upcoming else None}
    db.add(CrmActivity(business_id=business.id, type="follow_up_done", from_stage=None, to_stage=business.crm_stage,
                       note=f"Takip tamamlandı: {result}" + (f" — {text}" if text else ""), meta=meta,
                       created_by=user.name if user else "personel", user_id=user.id if user else None, created_at=now))
    if result != "Ulaşılamadı":
        business.last_contact_at = now
    fus.sync_cache(db, business)
    business.crm_last_action = f"Takip tamamlandı ({result})"
    business.crm_updated_at, business.crm_updated_by = now, (user.id if user else None)
    log_activity(db, user, "crm_follow_up_done", business_id=business.id, detail=f"{business.name}: takip tamamlandı ({result})", ip=ip)
    db.commit()


def history(db: Session, business_id: int, limit: int = 100) -> list[dict]:
    rows = (
        db.query(CrmActivity, User.name)
        .outerjoin(User, User.id == CrmActivity.user_id)
        .filter(CrmActivity.business_id == business_id)
        .order_by(CrmActivity.created_at.desc(), CrmActivity.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {"id": r.id, "type": r.type, "from_stage": r.from_stage, "to_stage": r.to_stage, "note": r.note, "created_at": r.created_at.isoformat(),
         "meta": r.meta, "user_id": r.user_id, "user_name": user_name or UNKNOWN_USER}
        for r, user_name in rows
    ]


def _user_name(db: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return user.name if user else None


def sales_fields(db: Session, business: Business) -> dict:
    """CRM satış takibi alanları (kart/detay çıktısı için)."""
    return {
        "crm_owner_id": business.crm_owner_id, "crm_owner_name": _user_name(db, business.crm_owner_id),
        "next_follow_up_at": business.next_follow_up_at, "follow_up_note": business.follow_up_note, "follow_up_state": follow_up_state(business),
        "last_contact_at": business.last_contact_at, "interested_service": business.interested_service,
        "offer_amount": float(business.offer_amount) if business.offer_amount is not None else None,
        "sale_amount": float(business.sale_amount) if business.sale_amount is not None else None, "lost_reason": business.lost_reason,
    }


def crm_state(db: Session, business: Business) -> dict:
    return {
        "in_crm": in_crm(business), "crm_stage": business.crm_stage, "staff_note": business.staff_note,
        "crm_added_at": business.crm_added_at, "crm_updated_at": business.crm_updated_at,
        "crm_added_by_name": _user_name(db, business.crm_added_by) or (UNKNOWN_USER if in_crm(business) else None),
        "crm_updated_by_name": _user_name(db, business.crm_updated_by) or (UNKNOWN_USER if in_crm(business) else None),
        "crm_last_action": business.crm_last_action, **sales_fields(db, business), "follow_ups": pending_follow_ups(db, business.id),
        "history": history(db, business.id),
    }


def normalize_legacy_stages(db: Session) -> int:
    """DB'de kalmış eski durum adlarını (Teklif Verildi, Takipte, Müşteri Oldu, Olumsuz …) yeni adlara çevirir. IDEMPOTENT ve yalnızca ad eşlemesidir (kayıt silinmez).

    Neden: Migration'dan sonra hâlâ ESKİ kodla çalışan bir sunucu/işçi süreci yeni kayıtlara eski adı yazabilir; API her açılışta bunu düzeltir.
    """
    from sqlalchemy import text

    from packages.crm import LEGACY_STAGE_ALIASES

    changed = 0
    db.execute(text("SET LOCAL lock_timeout = '3s'"))  # canlı bir iş satırları kilitliyse API açılışını bekletmez (hata yakalanır, sonraki açılışta yeniden denenir)
    for old, new in LEGACY_STAGE_ALIASES.items():
        for table, column in (("businesses", "crm_stage"), ("crm_activities", "from_stage"), ("crm_activities", "to_stage")):
            if not db.execute(text(f"SELECT 1 FROM {table} WHERE {column} = :old LIMIT 1"), {"old": old}).first():
                continue  # değişecek kayıt yoksa kilit alınmaz
            changed += db.execute(text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"), {"old": old, "new": new}).rowcount or 0
    db.commit()
    return changed


def log_contact(db: Session, business: Business, channel: str, result: str, note: str | None = None, *, user: User | None = None, ip: str | None = None) -> None:
    """İletişim kaydı (arama/WhatsApp/e-posta/yüz yüze) + SONUCU. Kayıt iletişim geçmişine yazılır; kimin ne zaman ne yaptığı bellidir.

    - CRM'de değilse firma 'Yeni' olarak CRM'e alınır (açık bir CRM işlemi).
    - Sonuç aşamayı şöyle etkiler: Ulaşılamadı → aşama değişmez (yalnızca deneme kaydı); Görüşüldü / Daha sonra aranacak → Yeni/Aranacak ise 'Arandı';
      İlgileniyor / Teklif istendi → 'Görüşüldü' (teklif aşamasındaysa değişmez); İlgilenmiyor → aşama değişmez (Kaybedildi'ye almak personelin kararıdır).
    - 'Ulaşılamadı' son görüşme tarihini güncellemez (görüşme gerçekleşmedi).
    """
    if channel not in CONTACT_CHANNELS:
        raise CrmError(422, f"Geçersiz iletişim türü. Geçerli: {', '.join(CONTACT_CHANNELS)}")
    if result not in CONTACT_RESULTS:
        raise CrmError(422, f"Geçersiz sonuç. Geçerli: {', '.join(CONTACT_RESULTS)}")
    if not in_crm(business):
        add_to_crm(db, business, DEFAULT_STAGE, None, user=user, ip=ip)
    now = datetime.now(timezone.utc)  # ekleme kaydından SONRA (geçmiş sıralaması: önce eklendi, sonra iletişim)
    old = business.crm_stage
    new = old
    if old not in (WON_STAGE, LOST_STAGE):
        if result in ("Görüşüldü", "Daha sonra aranacak") and old in ("Yeni", "Aranacak"):
            new = "Arandı"
        elif result in ("İlgileniyor", "Teklif istendi") and old in ("Yeni", "Aranacak", "Daha Sonra Ara", "Arandı", "Takip Bekliyor"):
            new = "Görüşüldü"
    text = _clean_note(note)
    label = f"{CONTACT_CHANNELS[channel]}: {result}"
    db.add(CrmActivity(business_id=business.id, type="contact", from_stage=old, to_stage=new, note=(f"{label} — {text}" if text else label),
                       meta={"channel": channel, "result": result}, created_by=user.name if user else "personel", user_id=user.id if user else None, created_at=now))
    business.crm_stage = new
    if result != "Ulaşılamadı":
        business.last_contact_at = now
    business.crm_last_action = label if new == old else f"{label} ({old} → {new})"
    business.crm_updated_at, business.crm_updated_by = now, (user.id if user else None)
    log_activity(db, user, "crm_contact", business_id=business.id, detail=f"{business.name}: {label}", ip=ip)
    db.commit()


def contact_attempts(db: Session, business_ids: list[int]) -> dict[int, int]:
    """Firma başına iletişim denemesi sayısı (contact kayıtları + 'Arandı' geçişleri)."""
    from sqlalchemy import func, or_

    if not business_ids:
        return {}
    rows = (
        db.query(CrmActivity.business_id, func.count(CrmActivity.id))
        .filter(CrmActivity.business_id.in_(business_ids),
                or_(CrmActivity.type == "contact", (CrmActivity.type == "status_change") & (CrmActivity.to_stage == "Arandı")))
        .group_by(CrmActivity.business_id).all()
    )
    return dict(rows)


def pending_follow_ups(db: Session, business_id: int) -> list[dict]:
    rows = fus.pending_for(db, business_id)
    users = {u.id: u.name for u in db.query(User.id, User.name).filter(User.id.in_({r.user_id for r in rows if r.user_id})).all()} if rows else {}
    return [fus.to_dict(r, None, users) for r in rows]


def follow_up_list(db: Session, business_id: int, closed_limit: int = 10) -> list[dict]:
    """Firma detayı için takipler: önce bekleyenler (en yakın önce), sonra son kapananlar (Tamamlandı/İptal)."""
    from packages.db.models import FollowUp

    pending = fus.pending_for(db, business_id)
    closed = (
        db.query(FollowUp).filter(FollowUp.business_id == business_id, FollowUp.status != fus.PENDING)
        .order_by(FollowUp.completed_at.desc().nullslast(), FollowUp.id.desc()).limit(closed_limit).all()
    )
    rows = pending + closed
    users = {u.id: u.name for u in db.query(User.id, User.name).filter(User.id.in_({r.user_id for r in rows if r.user_id})).all()} if rows else {}
    return [fus.to_dict(r, None, users) for r in rows]
