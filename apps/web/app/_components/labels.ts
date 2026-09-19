// Kullanıcıya gösterilen tüm sabit metinler Türkçedir. Sistem kodları (status/severity vb.) burada çevrilir.

export const UNVERIFIED = "Doğrulanamadı";

export const JOB_STATUS_LABELS: Record<string, string> = {
  pending: "Sırada bekliyor",
  running: "İşletmeler taranıyor",
  completed: "Tarama tamamlandı",
  partial: "Tarama kısmen tamamlandı",
  failed: "Tarama başarısız oldu",
};

export const BUSINESS_STATUS_LABELS: Record<string, string> = {
  discovered: "Analiz bekliyor",
  analyzing: "Analiz ediliyor",
  analyzed: "Analiz edildi",
  analysis_failed: "Analiz başarısız",
};

export const ANALYSIS_STATUS_LABELS: Record<string, string> = {
  pending: "Sırada bekliyor",
  running: "Çalışıyor",
  completed: "Tamamlandı",
  partial: "Kısmen tamamlandı (web sitesine erişilemedi)",
  failed: "Başarısız",
};

export const STAGE_LABELS: Record<string, string> = {
  research: "Çok kaynaklı araştırma",
  google_profile: "Google profili",
  website: "Web sitesi",
  evidence_extraction: "Kanıt çıkarımı",
  rule_engine: "Hizmet eşleştirme",
  scoring: "Satış değerlendirmesi",
  competitor: "Rakip karşılaştırma",
  ai_interpretation: "Yapay zekâ yorumu",
};

export const STAGE_STATUS_LABELS: Record<string, string> = {
  success: "Başarılı",
  cached: "Önbellekten (7 gün içinde araştırıldı)",
  failed: "Başarısız",
  skipped: "Atlandı",
};

export const SEVERITY_LABELS: Record<string, string> = { high: "Yüksek", medium: "Orta", low: "Düşük", none: "-" };
export const CONFIDENCE_LABELS: Record<string, string> = { high: "Yüksek", medium: "Orta", low: "Düşük" };
export const CHECK_STATUS_LABELS: Record<string, string> = { ok: "Sorun yok", problem: "Sorun", unknown: UNVERIFIED };
export const CATEGORY_LABELS: Record<string, string> = {
  website: "Web sitesi",
  seo: "SEO",
  gbp: "Google profili",
  social: "Sosyal medya",
};
export const SOURCE_LABELS: Record<string, string> = {
  places: "Google Places",
  listing: "Keşif kaydı",
  google_maps: "Google Haritalar",
  website_crawl: "Web sitesi taraması",
  pagespeed: "Google PageSpeed",
  osm_overpass: "Eski keşif kaydı (OpenStreetMap)",
  google_places: "Google Places",
  mock_demo: "Demo veri",
};

export const METRIC_STATUS_LABELS: Record<string, string> = {
  known: "Ölçüldü",
  not_available: UNVERIFIED,
  unknown: UNVERIFIED,
  unverified: "Doğrulanmadı",
};

// Keşif sırasında kaydedilen ölçümlerin Türkçe adları
export const DISCOVERY_METRIC_LABELS: Record<string, string> = {
  google_rating: "Google puanı",
  google_review_count: "Google yorum sayısı",
  photo_count: "Fotoğraf sayısı",
  website_present: "Web sitesi kayıtlı mı",
  phone_present: "Telefon kayıtlı mı",
  email_present: "E-posta kayıtlı mı",
};

export const AREA_LABELS: Record<string, string> = { website: "Web sitesi", gbp: "Google profili" };

export function metricLabel(key: string, storedLabel?: string): string {
  if (storedLabel) return `${AREA_LABELS[key.split(".")[0]] ?? ""}: ${storedLabel}`.replace(/^: /, "");
  if (DISCOVERY_METRIC_LABELS[key]) return DISCOVERY_METRIC_LABELS[key];
  if (key === "website.signals") return "Web sitesi ham tarama verisi";
  return key;
}

export const COMPETITOR_METRIC_LABELS: Record<string, string> = {
  google_rating: "Google puanı",
  google_review_count: "Yorum sayısı",
  website_present: "Web sitesi var mı",
  photo_count: "Fotoğraf sayısı",
};

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return UNVERIFIED;
  if (value === true) return "Evet";
  if (value === false) return "Hayır";
  return String(value);
}

/** Tüm tarih/saatler tarayıcı saat diliminden bağımsız olarak Europe/Istanbul'a göre gösterilir. */
export const TIME_ZONE = "Europe/Istanbul";

/** "18.09.2026 14:32" (Europe/Istanbul). */
export function formatIstanbul(iso: string | null | undefined): string {
  if (!iso) return UNVERIFIED;
  const parts = new Intl.DateTimeFormat("tr-TR", { timeZone: TIME_ZONE, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
    .formatToParts(new Date(iso))
    .reduce<Record<string, string>>((acc, p) => ({ ...acc, [p.type]: p.value }), {});
  return `${parts.day}.${parts.month}.${parts.year} ${parts.hour}:${parts.minute}`;
}

export function formatDateTime(iso: string | null | undefined): string {
  return formatIstanbul(iso);
}

export function trSort(a: string, b: string): number {
  return a.localeCompare(b, "tr");
}

export function levelClass(level: string | null): string {
  switch (level) {
    case "Yüksek": return "level-high";
    case "Orta": return "level-medium";
    case "Düşük": return "level-low";
    default: return "level-unknown";
  }
}

// ---- veri doğrulama durumları (çapraz doğrulama sonucu)
export const VERIFY_LABELS: Record<string, string> = {
  dogrulandi: "🟢 DOĞRULANDI",
  celiskili: "🟠 ÇELİŞKİLİ",
  bulunamadi: "🔴 BULUNAMADI",
  tek_kaynak: "⚪ TEK KAYNAK",
};
export const VERIFY_HELP: Record<string, string> = {
  dogrulandi: "Kaynaklardan doğrulandı.",
  celiskili: "Kaynaklar farklı bilgi veriyor — manuel kontrol gerekli.",
  bulunamadi: "Erişilebilen güvenilir kaynaklarda bulunamadı.",
  tek_kaynak: "Yalnızca güvenilirliği doğrulanmamış tek kaynakta var (ör. eski keşif kaydı).",
};

// ---- kaynak erişim durumları
export const SOURCE_STATE_LABELS: Record<string, string> = {
  kontrol_edildi: "KONTROL EDİLDİ",
  erisilemedi: "ERİŞİLEMEDİ",
  eslesme_yok: "EŞLEŞME YOK",
  atlandi: "ATLANDI",
};

export const FIELD_ORDER = [
  "name", "address", "phone", "website", "email", "rating", "review_count", "category", "maps_url", "hours",
  "description", "attributes", "last_review", "owner_replies", "cover_photo",
];

// ---- CRM
export const CRM_STAGES = ["Yeni", "Aranacak", "Daha Sonra Ara", "Arandı", "Görüşüldü", "Teklif Gönderildi", "Takip Bekliyor", "Kazanıldı", "Kaybedildi"] as const;
/** CRM özetindeki renk noktaları */
export const CRM_DOTS: Record<string, string> = {
  Yeni: "⚪", Aranacak: "🟡", "Daha Sonra Ara": "🟠", Arandı: "🔷", Görüşüldü: "🔵", "Teklif Gönderildi": "🟣", "Takip Bekliyor": "🟤", Kazanıldı: "🟢", Kaybedildi: "🔴",
};
export const CONTACT_CHANNELS: { key: string; label: string }[] = [{ key: "arama", label: "📞 Arama" }, { key: "whatsapp", label: "💬 WhatsApp" }, { key: "eposta", label: "📧 E-posta" }, { key: "yuz_yuze", label: "🤝 Yüz yüze" }];
export const CONTACT_RESULTS = ["Ulaşılamadı", "Görüşüldü", "İlgileniyor", "Teklif istendi", "İlgilenmiyor", "Daha sonra aranacak"];
/** CRM işleminden dönen durumdaki TÜM alanları firma nesnesine yansıtan yama (sahip/takip/teklif/satış dahil). */
export function crmPatch(state: {
  in_crm: boolean; crm_stage: string; staff_note: string | null; crm_added_at: string | null; crm_updated_at: string | null;
  crm_added_by_name?: string | null; crm_updated_by_name?: string | null; crm_last_action?: string | null; crm_owner_id?: number | null; crm_owner_name?: string | null;
  next_follow_up_at?: string | null; follow_up_note?: string | null; follow_up_state?: "overdue" | "today" | "upcoming" | null; last_contact_at?: string | null;
  interested_service?: string | null; offer_amount?: number | null; sale_amount?: number | null; lost_reason?: string | null;
}) {
  return {
    in_crm: state.in_crm, crm_stage: state.crm_stage, staff_note: state.staff_note, crm_added_at: state.crm_added_at, crm_updated_at: state.crm_updated_at,
    crm_added_by_name: state.crm_added_by_name ?? null, crm_updated_by_name: state.crm_updated_by_name ?? null, crm_last_action: state.crm_last_action ?? null,
    crm_owner_id: state.crm_owner_id ?? null, crm_owner_name: state.crm_owner_name ?? null, next_follow_up_at: state.next_follow_up_at ?? null,
    follow_up_note: state.follow_up_note ?? null, follow_up_state: state.follow_up_state ?? null, last_contact_at: state.last_contact_at ?? null,
    interested_service: state.interested_service ?? null, offer_amount: state.offer_amount ?? null, sale_amount: state.sale_amount ?? null, lost_reason: state.lost_reason ?? null,
  };
}
export const LOST_REASONS = ["Bütçe uygun değil", "Rakip ile çalışıyor", "İhtiyaç duymuyor", "Karar vericiye ulaşılamadı", "Zamanlama uygun değil", "Fiyatı yüksek buldu", "Diğer"];

const tl = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 });
/** Para tutarı (TL). Değer yoksa uydurma yerine "—" döner. */
export function formatTL(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${tl.format(value)} TL`;
}
/** Takip tarihi (Europe/Istanbul); saat 00:00 ise yalnızca gün gösterilir. */
export function formatFollowUp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const day = new Intl.DateTimeFormat("tr-TR", { timeZone: "Europe/Istanbul", day: "2-digit", month: "2-digit", year: "numeric" }).format(d);
  const time = new Intl.DateTimeFormat("tr-TR", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(d);
  return time === "00:00" ? day : `${day} ${time}`;
}
export const FOLLOW_UP_STATE_LABELS: Record<string, string> = { overdue: "⏰ Gecikmiş", today: "📅 Bugün", upcoming: "🗓️ Yaklaşan" };

export const OPP_ICONS: Record<string, string> = { Yüksek: "🔴", Orta: "🟠", Düşük: "🟡", Doğrulanmadı: "⚪" };
export const OPP_LEVEL_LABELS: Record<string, string> = { Yüksek: "Yüksek Fırsat", Orta: "Orta Fırsat", Düşük: "Düşük Fırsat", Doğrulanmadı: "Doğrulanmadı (olası)" };

export const GUIDE_SECTION_TITLES = {
  what: "A) Sorun nedir?",
  why: "B) Neden önemli?",
  solution: "C) Mchttasarım nasıl çözer?",
  steps: "D) Adım adım ne yapacağız?",
  pitch: "E) Müşteriye nasıl anlatılır?",
  offer: "F) Müşteriye hangi hizmeti teklif edeceğiz?",
  questions: "G) Personelin müşteriye soracağı sorular",
  verify: "H) İşlem sonrası kontrol",
} as const;

export const SORT_OPTIONS = [
  { value: "priority", label: "Öncelik (önerilen)" },
  { value: "score", label: "Satış puanı (yüksekten düşüğe)" },
  { value: "rating", label: "Google puanı (yüksekten düşüğe)" },
  { value: "reviews", label: "Yorum sayısı (çoktan aza)" },
  { value: "name", label: "İşletme adı (A → Z)" },
] as const;

/** Türkiye numarasını 10 haneli ulusal biçime çevirir ("0264 277 45 05" → "2642774505"); geçerli değilse null. */
export function nationalPhone(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let d = raw.replace(/\D/g, "");
  if (d.startsWith("0090")) d = d.slice(4);
  else if (d.startsWith("90") && d.length === 12) d = d.slice(2);
  else if (d.startsWith("0") && d.length === 11) d = d.slice(1);
  return d.length === 10 && "2345".includes(d[0]) ? d : null;
}
export const telUrl = (phone: string | null | undefined): string | null => {
  const n = nationalPhone(phone);
  return n ? `tel:+90${n}` : null;
};
/** WhatsApp yalnızca cep numaralarında (5xx) anlamlıdır; sabit hatta bağlantı verilmez. */
export const whatsappUrl = (phone: string | null | undefined): string | null => {
  const n = nationalPhone(phone);
  return n && n.startsWith("5") ? `https://wa.me/90${n}` : null;
};
