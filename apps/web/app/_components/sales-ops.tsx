"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Business, CallToday, CrmState, FollowUpItem, FollowUps, Funnel, PlanOpportunity, Revenue, SalesPlan, SalesSuggestions } from "@/lib/types";
import { useAuth } from "./auth";
import { Modal } from "./modal";
import { CONTACT_CHANNELS, CONTACT_RESULTS, CRM_DOTS, FOLLOW_UP_STATE_LABELS, LOST_REASONS, formatFollowUp, formatIstanbul, formatTL, telUrl, whatsappUrl } from "./labels";

const nf = new Intl.NumberFormat("tr-TR");

/** Yerel tarihten (tarayıcı saati) "YYYY-MM-DD"; ileri tarih seçimi için başlangıç değeri. Sunucu Europe/Istanbul takvim gününü esas alır. */
function isoDay(offsetDays = 0): string {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Istanbul" }).format(d);
}

/** Hızlı eylemler: Ara · WhatsApp · Web sitesi · Google Maps · E-posta. Yalnızca gerçek veriden gelen bağlantılar etkin olur. */
export function QuickActions({ business: b }: { business: Business }) {
  const tel = telUrl(b.phone);
  const wa = whatsappUrl(b.phone);
  const site = b.verification?.website;
  const verifiedSite = site?.status === "dogrulandi" && site.value ? site.value : null;
  const mail = b.email || (b.verification?.email?.status === "dogrulandi" ? b.verification.email.value : null);
  return (
    <div className="quick-actions" style={{ margin: "8px 0 0" }}>
      {tel ? <a className="qa-btn" href={tel}>📞 Ara</a> : <span className="qa-btn qa-disabled" title="Telefon doğrulanamadı">📞 Telefon yok</span>}
      {wa ? <a className="qa-btn" href={wa} target="_blank" rel="noreferrer">💬 WhatsApp</a> : <span className="qa-btn qa-disabled" title="Telefon doğrulanamadı">💬 WhatsApp</span>}
      {verifiedSite ? <a className="qa-btn" href={verifiedSite} target="_blank" rel="noreferrer">🌐 Web Sitesi</a> : <span className="qa-btn qa-disabled" title="Doğrulanmış web sitesi yok">🌐 Web sitesi doğrulanamadı</span>}
      <a className="qa-btn" href={b.maps_url ?? b.maps_search_url} target="_blank" rel="noreferrer">📍 Google Maps</a>
      {mail ? <a className="qa-btn" href={`mailto:${mail}`}>📧 E-posta</a> : <span className="qa-btn qa-disabled" title="E-posta doğrulanamadı">📧 E-posta yok</span>}
    </div>
  );
}

// ================================================================ takip tamamlama
export function FollowUpDoneForm({ business, results, onDone, onCancel }: { business: Pick<Business, "id" | "name">; results: string[]; onDone: (s: CrmState) => void; onCancel?: () => void }) {
  const [result, setResult] = useState(results[0] ?? "Görüşüldü");
  const [note, setNote] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true); setError(null);
    try {
      onDone(await api.completeFollowUp(business.id, { result, note: note.trim() || undefined, next_follow_up_at: next || null }));
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }
  return (
    <div className="followup-form" data-followup-form={business.id}>
      <div className="form-row" style={{ marginBottom: 6 }}>
        <div className="form-field"><label htmlFor={`fu-res-${business.id}`}>Takip sonucu</label>
          <select id={`fu-res-${business.id}`} value={result} onChange={(e) => setResult(e.target.value)}>{results.map((r) => <option key={r} value={r}>{r}</option>)}</select></div>
        <div className="form-field"><label htmlFor={`fu-next-${business.id}`}>Yeni takip tarihi (isteğe bağlı)</label>
          <input id={`fu-next-${business.id}`} type="date" min={isoDay(0)} value={next} onChange={(e) => setNext(e.target.value)} /></div>
      </div>
      <div className="form-field"><label htmlFor={`fu-note-${business.id}`}>Not</label><textarea id={`fu-note-${business.id}`} rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></div>
      {error && <p className="error small" role="alert">{error}</p>}
      <div className="actions"><button className="primary" disabled={busy} onClick={submit}>{busy ? "Kaydediliyor…" : "✓ Takibi Tamamla"}</button>{onCancel && <button className="secondary" onClick={onCancel}>Vazgeç</button>}</div>
    </div>
  );
}

/** Takip oluştur / düzenle / iptal: tarih + saat (isteğe bağlı) + not (+ sorumlu). */
export function FollowUpModal({ business, followUp, onClose, onSaved }: { business: Pick<Business, "id" | "name">; followUp?: FollowUpItem; onClose: () => void; onSaved: () => void }) {
  const { can } = useAuth();
  const initialDate = followUp ? new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Istanbul" }).format(new Date(followUp.due_at)) : "";
  const initialTime = followUp?.has_time ? new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(followUp.due_at)) : "";
  const [date, setDate] = useState(initialDate);
  const [time, setTime] = useState(initialTime);
  const [note, setNote] = useState(followUp?.note ?? "");
  const [owner, setOwner] = useState(followUp?.user_id?.toString() ?? "");
  const [owners, setOwners] = useState<{ id: number; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canAssign = can("crm_assign");
  useEffect(() => { if (canAssign) api.getCrmOwners().then(setOwners).catch(() => setOwners([])); }, [canAssign]);

  async function save() {
    if (!date) { setError("Takip tarihi seçin."); return; }
    setBusy(true); setError(null);
    const due = time ? `${date}T${time}:00+03:00` : date; // Europe/Istanbul (UTC+3)
    try {
      if (followUp) await api.patchFollowUp(followUp.id, { due_at: due, note: note.trim() || null, ...(canAssign ? { user_id: owner ? Number(owner) : null } : {}) });
      else await api.createFollowUp({ business_id: business.id, due_at: due, note: note.trim() || null, ...(canAssign && owner ? { user_id: Number(owner) } : {}) });
      onSaved(); onClose();
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }
  async function cancelFollowUp() {
    if (!followUp || !window.confirm("Bu takip iptal edilsin mi? (Kayıt silinmez, İptal olarak kalır.)")) return;
    setBusy(true);
    try { await api.patchFollowUp(followUp.id, { status: "İptal" }); onSaved(); onClose(); } catch (e) { setError((e as Error).message); setBusy(false); }
  }
  return (
    <Modal title={followUp ? "✏️ Takibi Düzenle" : "📅 Takip Planla"} onClose={onClose}>
      <p><strong>{business.name}</strong></p>
      <div className="form-row">
        <div className="form-field"><label htmlFor="fm-date">Tarih</label><input id="fm-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
        <div className="form-field narrow"><label htmlFor="fm-time">Saat (isteğe bağlı)</label><input id="fm-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} /></div>
      </div>
      {canAssign && (
        <div className="form-field"><label htmlFor="fm-owner">Sorumlu</label>
          <select id="fm-owner" value={owner} onChange={(e) => setOwner(e.target.value)}><option value="">Varsayılan (firmanın sorumlusu / ben)</option>{owners.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></div>
      )}
      <div className="form-field"><label htmlFor="fm-note">Not</label><textarea id="fm-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Örn. Teklif için geri dön." /></div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="guide-actions">
        <button className="primary" id="fm-save" disabled={busy} onClick={save}>{busy ? "Kaydediliyor…" : "Kaydet"}</button>
        {followUp && <button className="secondary" id="fm-cancel-followup" disabled={busy} onClick={cancelFollowUp}>✕ Takibi İptal Et</button>}
        <button className="secondary" onClick={onClose}>Vazgeç</button>
      </div>
    </Modal>
  );
}

// ================================================================ 📅 takip paneli (ana sayfa)
export function FollowUpsPanel({ version, onChanged }: { version: number; onChanged?: () => void }) {
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [data, setData] = useState<FollowUps | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.getFollowUps(scope).then((r) => { if (!cancelled) { setData(r); setError(null); } }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [scope, version, tick]);

  const row = (b: Business) => (
    <li key={b.id} className={`followup-row fu-${b.follow_up_state}`} data-followup-id={b.id}>
      <div className="followup-head">
        <div>
          <Link href={`/businesses/${b.id}`}><strong>{b.name}</strong></Link>
          <div className="muted small">{FOLLOW_UP_STATE_LABELS[b.follow_up_state ?? "upcoming"]} · {formatFollowUp(b.next_follow_up_at)} · {CRM_DOTS[b.crm_stage]} {b.crm_stage}{b.crm_owner_name ? ` · ${b.crm_owner_name}` : ""}</div>
          {b.follow_up_note && <div className="small">📝 {b.follow_up_note}</div>}
        </div>
        <button className="secondary" onClick={() => setOpen(open === b.id ? null : b.id)}>{open === b.id ? "Kapat" : "✓ Tamamla"}</button>
      </div>
      <QuickActions business={b} />
      {open === b.id && data && <FollowUpDoneForm business={b} results={data.results} onCancel={() => setOpen(null)} onDone={() => { setOpen(null); setTick((n) => n + 1); onChanged?.(); }} />}
    </li>
  );

  return (
    <section className="card side-card" id="followups-panel" aria-label="Takipler">
      <h2>📅 TAKİPLER</h2>
      <div className="chips" style={{ marginBottom: 8 }}>
        <button className={`chip ${scope === "mine" ? "active" : ""}`} onClick={() => setScope("mine")}>Benim</button>
        <button className={`chip ${scope === "all" ? "active" : ""}`} onClick={() => setScope("all")}>Tümü</button>
      </div>
      {error && <p className="error small">Takipler alınamadı: {error}</p>}
      {!data && !error && <p className="muted small">Yükleniyor…</p>}
      {data && (
        <>
          <h3 className="fu-title fu-overdue-title">🚨 Gecikmiş Takipler <span data-testid="fu-overdue-count">({data.counts.overdue})</span></h3>
          {data.overdue.length === 0 ? <p className="muted small">Geciken takip yok.</p> : <ul className="followup-list" id="followups-overdue">{data.overdue.map(row)}</ul>}
          <h3 className="fu-title">📅 Bugünkü Takipler <span data-testid="fu-today-count">({data.counts.today})</span></h3>
          {data.today.length === 0 ? <p className="muted small">Bugün için planlı takip yok.</p> : <ul className="followup-list" id="followups-today">{data.today.map(row)}</ul>}
          <h3 className="fu-title">🗓️ Yarın <span data-testid="fu-tomorrow-count">({data.counts.tomorrow})</span></h3>
          {data.tomorrow.length === 0 ? <p className="muted small">Yarın için planlı takip yok.</p> : <ul className="followup-list" id="followups-tomorrow">{data.tomorrow.map(row)}</ul>}
          <details className="fu-week">
            <summary>📆 Bu Hafta <span data-testid="fu-week-count">({data.counts.week})</span></summary>
            {data.week.length === 0 ? <p className="muted small">Bu hafta planlı takip yok.</p> : <ul className="followup-list" id="followups-week">{data.week.map(row)}</ul>}
          </details>
          {data.counts.upcoming > 0 && <p className="muted small">Daha ileri tarihli takip: {data.counts.upcoming} (CRM ekranında “Takip” filtresiyle görün)</p>}
        </>
      )}
    </section>
  );
}

// ================================================================ 🔥 Bugün Kimi Aramalıyım?
export function CallTodayPanel({ version, onChanged }: { version: number; onChanged?: () => void }) {
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [data, setData] = useState<CallToday | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [planFor, setPlanFor] = useState<Business | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.getCallToday(scope, 10).then((r) => { if (!cancelled) { setData(r); setError(null); } }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [scope, version, tick]);

  return (
    <section className="card today" id="call-today-panel" aria-label="Bugün kimi aramalıyım">
      <h2>🔥 BUGÜN KİMİ ARAMALIYIM?</h2>
      <p className="muted small">
        Satış öncelik puanına göre sıralanır: gerçek fırsat, aciliyet, hizmet uyumu, ticari yapı, dijital durum, iletişim bilgisi ve CRM/takip durumu birlikte değerlendirilir.
        Bu puan “satış fırsatı skoru”ndan farklıdır: bugün kimi aramanın en verimli olacağını gösterir. Kapanmış, takip tarihi ileri olan ve bugün görüşülmüş kayıtlar listelenmez.
      </p>
      <div className="chips" style={{ marginBottom: 8 }}>
        <button className={`chip ${scope === "mine" ? "active" : ""}`} onClick={() => setScope("mine")}>Benim + sahipsiz</button>
        <button className={`chip ${scope === "all" ? "active" : ""}`} onClick={() => setScope("all")}>Tüm ekip</button>
      </div>
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">Yükleniyor…</p>}
      {data && data.items.length === 0 && <p className="muted" id="call-today-empty">Şu anda aranacak uygun kayıt bulunmuyor. Analiz tamamlanan firmalar burada sıralanır.</p>}
      {data && data.items.length > 0 && (
        <ol className="call-list" id="call-today-list">
          {data.items.map(({ business: b, call }) => (
            <li key={b.id} className="call-item" data-call-id={b.id}>
              <div className="call-head">
                <div>
                  <Link href={`/businesses/${b.id}`}><strong>{b.name}</strong></Link>
                  <div className="muted small">{b.sector_name} · {b.province_name ?? "—"}{b.district_name ? ` / ${b.district_name}` : ""} · {b.phone ?? <span className="unverified">Telefon doğrulanamadı</span>}</div>
                  <div className="call-sources">{call.sources.map((s) => <span key={s.key} className={`src-tag src-${s.key}`} data-call-source={s.key}>{s.label}</span>)}</div>
                  <div className="small">{b.in_crm ? `${CRM_DOTS[b.crm_stage]} ${b.crm_stage}` : "CRM'de değil"}{b.follow_up_state ? ` · ${FOLLOW_UP_STATE_LABELS[b.follow_up_state]}` : ""} · <strong>Sonraki adım:</strong> {call.next_action}</div>
                </div>
                <div className="call-score" title="Satış öncelik puanı (0-100)"><span data-testid="call-score">{call.score}</span><small>/100</small></div>
              </div>
              <QuickActions business={b} />
              <div className="quick-actions call-actions" style={{ margin: "6px 0 0" }}>
                <Link className="qa-btn" href={`/businesses/${b.id}#crm-panel`} data-call-action="ara" title="Aramayı sistem yapmaz: arama hazırlığı ve iletişim kaydı için firma sayfasını açar">📞 ARA</Link>
                <Link className="qa-btn" href={`/businesses/${b.id}`} data-call-action="analiz">🔎 ANALİZ</Link>
                <button className="qa-btn" data-call-action="takip" onClick={() => setPlanFor(b)}>📅 TAKİP PLANLA</button>
                <Link className="qa-btn" href={`/businesses/${b.id}#crm-sales-section`} data-call-action="teklif">📄 TEKLİF OLUŞTUR</Link>
              </div>
              <button className="link-btn small" onClick={() => setOpen(open === b.id ? null : b.id)} aria-expanded={open === b.id}>{open === b.id ? "▲ Gerekçeyi gizle" : "▼ Neden bugün aranmalı?"}</button>
              {open === b.id && (
                <div className="call-why" data-call-why={b.id}>
                  <ul>{call.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
                  <div className="muted small">Puan bileşenleri: {Object.entries(call.components).map(([k, v]) => `${COMPONENT_LABELS[k] ?? k} ${v}/${call.weights[k]}`).join(" · ")}</div>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
      {planFor && <FollowUpModal business={planFor} onClose={() => setPlanFor(null)} onSaved={() => { setTick((n) => n + 1); onChanged?.(); }} />}
      {data && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {data.eligible} uygun aday ({data.total_candidates} incelendi).
          {Object.keys(data.excluded).length > 0 && <> Elenenler: {Object.entries(data.excluded).map(([k, v]) => `${k} (${v})`).join(" · ")}.</>}
        </p>
      )}
    </section>
  );
}

const COMPONENT_LABELS: Record<string, string> = { opportunity: "fırsat", urgency: "aciliyet", service_fit: "hizmet uyumu", commercial: "ticari yapı", digital: "dijital durum", competitor: "rakip", contact: "iletişim", crm: "CRM/takip" };

// ================================================================ satış hunisi + para nereden geliyor
const PERIOD_CHOICES: { key: string; label: string }[] = [{ key: "today", label: "Bugün" }, { key: "week", label: "Hafta" }, { key: "month", label: "Ay" }, { key: "total", label: "Toplam" }];

export function PeriodChips({ value, onChange }: { value: string; onChange: (p: string) => void }) {
  return (
    <div className="chips" style={{ marginBottom: 8 }}>
      {PERIOD_CHOICES.map((p) => <button key={p.key} className={`chip ${value === p.key ? "active" : ""}`} data-period-choice={p.key} onClick={() => onChange(p.key)}>{p.label}</button>)}
    </div>
  );
}

export function FunnelCard({ version }: { version: number }) {
  const [period, setPeriod] = useState("total");
  const [data, setData] = useState<Funnel | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.getFunnel(period).then((r) => { if (!cancelled) { setData(r); setError(null); } }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [period, version]);
  const max = data ? Math.max(1, ...data.steps.map((s) => s.count)) : 1;
  return (
    <section className="card side-card" id="funnel-card" aria-label="Satış hunisi">
      <h2>🔻 SATIŞ HUNİSİ</h2>
      <PeriodChips value={period} onChange={setPeriod} />
      {error && <p className="error small">{error}</p>}
      {!data && !error && <p className="muted small">Yükleniyor…</p>}
      {data && (
        <>
          <ul className="funnel-list">
            {data.steps.map((s) => (
              <li key={s.key} data-funnel-step={s.key}>
                <div className="funnel-row"><span>{s.label}</span><strong data-testid={`funnel-${s.key}`}>{nf.format(s.count)}</strong></div>
                <div className="funnel-bar"><span style={{ width: `${Math.max(2, (100 * s.count) / max)}%` }} /></div>
                <div className="muted small">{s.rate_from_previous !== null ? `önceki adımdan %${s.rate_from_previous}` : " "}</div>
              </li>
            ))}
          </ul>
          <dl className="funnel-money">
            <div><dt>Teklif toplamı</dt><dd data-testid="funnel-offer-total">{formatTL(data.offer_total)}</dd><small className="muted">{data.offer_count} teklif{data.offer_amount_missing ? ` (${data.offer_amount_missing} tanesinde tutar girilmedi)` : ""}</small></div>
            <div><dt>Kazanılan toplam</dt><dd data-testid="funnel-won-total">{formatTL(data.won_total)}</dd><small className="muted">{data.won_count} satış{data.won_amount_missing ? ` (${data.won_amount_missing} tanesinde tutar girilmedi)` : ""}</small></div>
          </dl>
          <p className="muted small">{data.note} Güncelleme: {formatIstanbul(data.updated_at).slice(-5)} · Europe/Istanbul</p>
        </>
      )}
    </section>
  );
}

export function RevenueCard({ version }: { version: number }) {
  const [by, setBy] = useState<"service" | "sector">("service");
  const [period, setPeriod] = useState("total");
  const [data, setData] = useState<Revenue | null>(null);
  const [sugg, setSugg] = useState<SalesSuggestions | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.getRevenue(by, period).then((r) => { if (!cancelled) { setData(r); setError(null); } }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [by, period, version]);
  useEffect(() => { api.getSalesSuggestions().then(setSugg).catch(() => setSugg(null)); }, [version]);
  const rows = (data?.items ?? []).filter((r) => r.opportunities || r.offers || r.sales).slice(0, 8);
  return (
    <section className="card side-card" id="revenue-card" aria-label="Para nereden geliyor">
      <h2>💰 PARA NEREDEN GELİYOR?</h2>
      <div className="chips" style={{ marginBottom: 6 }}>
        <button className={`chip ${by === "service" ? "active" : ""}`} onClick={() => setBy("service")}>Hizmete göre</button>
        <button className={`chip ${by === "sector" ? "active" : ""}`} onClick={() => setBy("sector")}>Sektöre göre</button>
      </div>
      <PeriodChips value={period} onChange={setPeriod} />
      {error && <p className="error small">{error}</p>}
      {data && rows.length === 0 && <p className="muted small">Henüz gösterilecek fırsat/teklif/satış kaydı yok.</p>}
      {data && rows.length > 0 && (
        <div className="table-scroll">
          <table className="mini-table" id="revenue-table">
            <thead><tr><th>{by === "service" ? "Hizmet" : "Sektör"}</th><th title="Şu an tespit edilen fırsat">Fırsat</th><th>Teklif</th><th>Satış</th><th>Tutar</th><th>Ort.</th><th>Dönüşüm</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name} data-revenue-row={r.name}>
                  <td>{r.name}</td><td>{nf.format(r.opportunities)}</td><td>{r.offers}</td><td>{r.sales}</td>
                  <td>{formatTL(r.amount)}{r.amount_missing ? <span className="muted small" title="Tutarı girilmemiş satış"> *</span> : null}</td>
                  <td>{formatTL(r.average)}</td>
                  <td>{r.conversion !== null ? `%${r.conversion}` : <span className="muted small" title={r.sample_note ?? ""}>{r.sample_note ?? "—"}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">{data?.note} Dönüşüm en az {data?.min_sample ?? 5} teklif olduğunda hesaplanır. * = tutarı girilmemiş satış var.</p>
      {sugg && sugg.items.length > 0 && (
        <div className="suggestions" id="sales-suggestions">
          <div className="label-cap">Veriye dayalı öneriler</div>
          <ul>{sugg.items.map((s, i) => <li key={i} className="small">{s.text}</li>)}</ul>
        </div>
      )}
    </section>
  );
}

// ================================================================ CRM satış takibi bölümü (firma detayı)
export function CrmSalesSection({ business, onUpdated, followUps = [], onReload }: { business: Business; onUpdated: (state: CrmState) => void; followUps?: FollowUpItem[]; onReload?: () => void }) {
  const { can } = useAuth();
  const [editing, setEditing] = useState(false);
  const [owners, setOwners] = useState<{ id: number; name: string }[]>([]);
  const [services, setServices] = useState<string[]>([]);
  const [form, setForm] = useState({ offer_amount: "", sale_amount: "", lost_reason: "", interested_service: "", owner_id: "" });
  const [results, setResults] = useState<string[]>([]);
  const [fuModal, setFuModal] = useState<{ item?: FollowUpItem } | null>(null);
  const [completingId, setCompletingId] = useState<number | null>(null);
  const [contactOpen, setContactOpen] = useState(false);
  const [contact, setContact] = useState({ channel: "arama", result: "Ulaşılamadı", note: "" });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const canAssign = can("crm_assign");
  useEffect(() => { if (canAssign) api.getCrmOwners().then(setOwners).catch(() => setOwners([])); }, [canAssign]);
  useEffect(() => { api.getFollowUps("mine").then((r) => setResults(r.results)).catch(() => setResults([])); }, []);
  useEffect(() => { api.getCrmServices().then(setServices).catch(() => setServices([])); }, []);

  function startEdit() {
    setForm({
      offer_amount: business.offer_amount?.toString() ?? "", sale_amount: business.sale_amount?.toString() ?? "", lost_reason: business.lost_reason ?? "",
      interested_service: business.interested_service ?? "", owner_id: business.crm_owner_id?.toString() ?? "",
    });
    setEditing(true); setMessage(null);
  }

  async function save() {
    setSaving(true); setMessage(null);
    const body: Record<string, unknown> = {
      offer_amount: form.offer_amount || null,
      interested_service: form.interested_service || null,
    };
    if (business.crm_stage === "Kazanıldı") body.sale_amount = form.sale_amount || null;
    if (business.crm_stage === "Kaybedildi") body.lost_reason = form.lost_reason || null;
    if (canAssign) body.owner_id = form.owner_id ? Number(form.owner_id) : null;
    try {
      onUpdated(await api.updateCrm(business.id, body));
      setEditing(false); setMessage({ ok: true, text: "✓ Satış bilgileri kaydedildi." });
    } catch (e) { setMessage({ ok: false, text: `Kaydedilemedi: ${(e as Error).message}` }); } finally { setSaving(false); }
  }

  async function saveContact() {
    setSaving(true); setMessage(null);
    try {
      onUpdated(await api.logContact(business.id, { channel: contact.channel, result: contact.result, note: contact.note.trim() || undefined }));
      setContactOpen(false); setContact({ channel: "arama", result: "Ulaşılamadı", note: "" });
      setMessage({ ok: true, text: "✓ İletişim kaydı eklendi." });
    } catch (e) { setMessage({ ok: false, text: `Kaydedilemedi: ${(e as Error).message}` }); } finally { setSaving(false); }
  }

  const closed = business.crm_stage === "Kazanıldı" || business.crm_stage === "Kaybedildi";
  return (
    <div className="crm-sales" id="crm-sales-section">
      <h3 style={{ marginTop: 18 }}>💼 SATIŞ TAKİBİ</h3>
      <dl className="crm-facts">
        <div><dt>Sorumlu personel</dt><dd data-testid="crm-owner">{business.crm_owner_name ?? "—"}</dd></div>
        <div><dt>Son görüşme</dt><dd>{business.last_contact_at ? formatIstanbul(business.last_contact_at) : "—"}</dd></div>
        <div><dt>İlgilenilen hizmet</dt><dd>{business.interested_service ?? "—"}</dd></div>
        <div><dt>Teklif tutarı</dt><dd data-testid="crm-offer-amount">{formatTL(business.offer_amount)}</dd></div>
        <div><dt>Satış tutarı</dt><dd data-testid="crm-sale-amount">{business.crm_stage === "Kazanıldı" ? (business.sale_amount !== null && business.sale_amount !== undefined ? formatTL(business.sale_amount) : <span className="unverified">Tutar girilmedi</span>) : "—"}</dd></div>
        {business.crm_stage === "Kaybedildi" && <div><dt>Kaybedilme nedeni</dt><dd data-testid="crm-lost-reason">{business.lost_reason ?? <span className="unverified">Girilmedi</span>}</dd></div>}
      </dl>
      {!editing && (
        <div className="actions">
          <button className="secondary" id="crm-contact-open" onClick={() => setContactOpen((o) => !o)}>📞 İletişim Kaydı Ekle</button>
          <button className="secondary" id="crm-sales-edit" onClick={startEdit}>✏️ Satış Bilgilerini Düzenle</button>
          <button className="secondary" id="crm-followup-add" disabled={business.crm_stage === "Kazanıldı" || business.crm_stage === "Kaybedildi"} onClick={() => setFuModal({})}>📅 Takip Planla</button>
        </div>
      )}
      {contactOpen && (
        <div className="crm-sales-form" id="crm-contact-form">
          <div className="form-row">
            <div className="form-field"><label htmlFor="cf-channel">İletişim türü</label>
              <select id="cf-channel" value={contact.channel} onChange={(e) => setContact({ ...contact, channel: e.target.value })}>{CONTACT_CHANNELS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</select></div>
            <div className="form-field"><label htmlFor="cf-result">Sonuç</label>
              <select id="cf-result" value={contact.result} onChange={(e) => setContact({ ...contact, result: e.target.value })}>{CONTACT_RESULTS.map((r) => <option key={r} value={r}>{r}</option>)}</select></div>
          </div>
          <div className="form-field"><label htmlFor="cf-note">Not</label><textarea id="cf-note" rows={2} value={contact.note} onChange={(e) => setContact({ ...contact, note: e.target.value })} /></div>
          <div className="actions"><button className="primary" id="cf-save" disabled={saving} onClick={saveContact}>{saving ? "Kaydediliyor…" : "Kaydet"}</button><button className="secondary" onClick={() => setContactOpen(false)}>Vazgeç</button></div>
        </div>
      )}
      <div className="fu-list" id="crm-follow-ups">
        <div className="label-cap">Takipler</div>
        {followUps.length === 0 ? <p className="muted small">Bu firma için takip yok.</p> : (
          <ul className="followup-list">
            {followUps.map((f) => (
              <li key={f.id} className={`followup-row ${f.status === "Bekliyor" ? `fu-${f.date_state}` : "fu-closed"}`} data-follow-up-id={f.id} data-follow-up-status={f.status}>
                <div className="followup-head">
                  <div>
                    <strong data-testid="fu-when">{formatFollowUp(f.due_at)}</strong>{" "}
                    {f.status === "Bekliyor" && f.date_state === "overdue" && <span className="fu-badge fu-overdue">🚨 Gecikmiş</span>}
                    {f.status === "Bekliyor" && f.date_state === "today" && <span className="fu-badge fu-today">📅 Bugün{f.time_passed ? " · saati geçti" : ""}</span>}
                    {f.status !== "Bekliyor" && <span className="fu-badge">{f.status === "Tamamlandı" ? "✅ Tamamlandı" : "✕ İptal"}{f.result ? ` · ${f.result}` : ""}</span>}
                    <div className="small muted">{f.user_name ? `Sorumlu: ${f.user_name}` : "Sorumlu: —"}{f.note ? ` · ${f.note}` : ""}</div>
                  </div>
                  {f.status === "Bekliyor" && (
                    <div className="row-actions">
                      <button className="secondary" data-fu-action="tamamla" onClick={() => setCompletingId(completingId === f.id ? null : f.id)}>✓ Tamamla</button>
                      <button className="secondary" data-fu-action="duzenle" onClick={() => setFuModal({ item: f })}>✏️ Düzenle</button>
                    </div>
                  )}
                </div>
                {completingId === f.id && (
                  <FollowUpDoneForm business={business} results={results} onCancel={() => setCompletingId(null)}
                    onDone={(s) => { setCompletingId(null); onUpdated(s); onReload?.(); setMessage({ ok: true, text: "✓ Takip tamamlandı." }); }} />
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      {fuModal && <FollowUpModal business={business} followUp={fuModal.item} onClose={() => setFuModal(null)} onSaved={() => { onReload?.(); setMessage({ ok: true, text: "✓ Takip kaydedildi." }); }} />}
      {editing && (
        <div className="crm-sales-form">
          <div className="form-row">
            <div className="form-field"><label htmlFor="sf-service">İlgilenilen hizmet</label>
              <input id="sf-service" list="sf-services" value={form.interested_service} onChange={(e) => setForm({ ...form, interested_service: e.target.value })} placeholder="Örn. Kurumsal Web Sitesi" />
              <datalist id="sf-services">{services.map((s) => <option key={s} value={s} />)}</datalist></div>
            <div className="form-field narrow"><label htmlFor="sf-offer">Teklif tutarı (TL)</label>
              <input id="sf-offer" inputMode="decimal" value={form.offer_amount} onChange={(e) => setForm({ ...form, offer_amount: e.target.value })} /></div>
            {business.crm_stage === "Kazanıldı" && <div className="form-field narrow"><label htmlFor="sf-sale">Satış tutarı (TL)</label>
              <input id="sf-sale" inputMode="decimal" value={form.sale_amount} onChange={(e) => setForm({ ...form, sale_amount: e.target.value })} /></div>}
          </div>
          {business.crm_stage === "Kaybedildi" && (
            <div className="form-field"><label htmlFor="sf-lost">Kaybedilme nedeni</label>
              <select id="sf-lost" value={form.lost_reason} onChange={(e) => setForm({ ...form, lost_reason: e.target.value })}><option value="">Seçin…</option>{LOST_REASONS.map((r) => <option key={r} value={r}>{r}</option>)}</select></div>
          )}
          {canAssign && (
            <div className="form-field"><label htmlFor="sf-owner">Sorumlu personel</label>
              <select id="sf-owner" value={form.owner_id} onChange={(e) => setForm({ ...form, owner_id: e.target.value })}><option value="">Atanmadı</option>{owners.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></div>
          )}
          {closed && <p className="muted small">Kapanmış (Kazanıldı/Kaybedildi) kayıtlarda takip tutulmaz; bekleyen takipler iptal edilir.</p>}
          <div className="actions"><button className="primary" id="crm-sales-save" disabled={saving} onClick={save}>{saving ? "Kaydediliyor…" : "Kaydet"}</button><button className="secondary" disabled={saving} onClick={() => setEditing(false)}>Vazgeç</button></div>
        </div>
      )}
      {message && <p role="status" className={message.ok ? "small crm-ok" : "error"}>{message.text}</p>}
    </div>
  );
}

// ================================================================ 💼 Satış planı: Ne satabilirim?
const LEVEL_STYLE: Record<string, string> = { satis: "lvl-satis", olasi: "lvl-olasi", zayif: "lvl-zayif", uygun_degil: "lvl-uygun" };

function OpportunityRow({ o }: { o: PlanOpportunity }) {
  const [open, setOpen] = useState(o.level === "satis" && o.priority !== null && o.priority <= 2);
  return (
    <li className={`plan-item ${LEVEL_STYLE[o.level]}`} data-plan-service={o.service} data-plan-level={o.level}>
      <button className="plan-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="plan-title">{o.level_label} · <strong>{o.service}</strong></span>
        <span className="plan-meta">
          {o.priority !== null && <span className="plan-prio" title="Satış önceliği">#{o.priority}</span>}
          {o.estimate && <span className={`plan-est ${o.estimate.priced ? "" : "unverified"}`} data-testid="plan-estimate">{o.estimate.label}</span>}
        </span>
      </button>
      <div className="small muted" style={{ padding: "0 12px" }}>Kaynak: {o.sources.join(" · ")}</div>
      {open && (
        <div className="plan-body">
          <p><strong>İhtiyaç:</strong> {o.need}</p>
          {o.why && <p><strong>Neden önemli:</strong> {o.why}</p>}
          <div><strong>Kanıt:</strong>
            {o.evidence.length === 0 ? <p className="unverified small">{o.evidence_note ?? "Doğrulanamadı"}</p> : (
              <ul className="small">{o.evidence.map((e, i) => (
                <li key={i}><span className={`src-chip src-${e.source_label}`}>{e.source_label}</span> {e.detail || e.text} {!e.verified && <em className="unverified">(doğrulanmadı)</em>}</li>
              ))}</ul>
            )}
          </div>
          <p><strong>Yaklaşım:</strong> {o.approach}</p>
          {o.caveat && <p className="small unverified">⚠️ {o.caveat}</p>}
          {o.guide_id && <Link className="qa-btn" href={`/rehber?guide=${o.guide_id}`}>💡 Nasıl çözülür?</Link>}
        </div>
      )}
    </li>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return <button className="secondary" onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { setDone(false); } }}>{done ? "✓ Kopyalandı" : label}</button>;
}

export function SalesPlanPanel({ business }: { business: Business }) {
  const [plan, setPlan] = useState<SalesPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showOthers, setShowOthers] = useState(false);
  const [script, setScript] = useState<"call" | "whatsapp" | "email" | "note">("call");

  const load = useCallback(() => api.getSalesPlan(business.id).then((p) => { setPlan(p); setError(null); }).catch((e) => setError(e.message)), [business.id]);
  useEffect(() => { load(); }, [load, business.last_analysis_at]);

  if (error) return <div className="card"><p className="error">Satış planı alınamadı: {error}</p></div>;
  if (!plan) return <div className="card"><p className="muted">Satış planı yükleniyor…</p></div>;
  if (!plan.analyzed) return <div className="card" id="sales-plan"><h2 style={{ marginTop: 0 }}>💼 SATIŞ PLANI</h2><p className="muted">{plan.message}</p></div>;

  const actionable = plan.opportunities.filter((o) => o.level === "satis" || o.level === "olasi");
  const others = plan.opportunities.filter((o) => o.level === "zayif" || o.level === "uygun_degil");
  const s = plan.scripts;
  const scriptText = s ? { call: s.call, whatsapp: s.whatsapp, email: `Konu: ${s.email.subject}\n\n${s.email.body}`, note: s.short_note }[script] : "";
  return (
    <div className="card" id="sales-plan">
      <h2 style={{ marginTop: 0 }}>💼 SATIŞ PLANI — Ne satabilirim?</h2>
      <p className="muted small">Her hizmet için ihtiyaç, kanıt ve kaynağı gösterilir. Kanıtı olmayan hiçbir şey olgu gibi yazılmaz; ölçülemeyen alanlar “Doğrulanamadı” olarak kalır.</p>

      {plan.package && (
        <div className="plan-package" id="plan-package">
          <div className="label-cap">Önerilen paket ve tahmini değer</div>
          <p style={{ margin: "4px 0" }}><strong>{plan.package.services.join(" + ") || "—"}</strong></p>
          <p style={{ margin: "4px 0", fontSize: 18 }} data-testid="package-estimate" className={plan.package.default === null ? "unverified" : ""}>{plan.package.label}</p>
          {plan.package.unpriced.length > 0 && plan.package.priced.length > 0 && <p className="small muted">Fiyatlandırılmamış (toplama dahil değil): {plan.package.unpriced.join(", ")}</p>}
          <p className="small muted">{plan.package.disclaimer}</p>
        </div>
      )}

      {actionable.length === 0 ? <p className="muted">Kanıta dayalı satılabilir bir hizmet fırsatı tespit edilmedi.</p> : <ul className="plan-list" id="plan-actionable">{actionable.map((o) => <OpportunityRow key={o.service} o={o} />)}</ul>}
      {others.length > 0 && (
        <>
          <button className="link-btn" onClick={() => setShowOthers(!showOthers)}>{showOthers ? "▲" : "▼"} Zayıf / uygun olmayan hizmetler ({others.length})</button>
          {showOthers && <ul className="plan-list">{others.map((o) => <OpportunityRow key={o.service} o={o} />)}</ul>}
        </>
      )}

      {plan.cross_check_flags && plan.cross_check_flags.length > 0 && (
        <div className="plan-flags" id="plan-flags">
          <h3>⚠️ Kaynaklar arası çelişki</h3>
          <ul className="small">{plan.cross_check_flags.map((f, i) => <li key={i}><strong>{f.field}:</strong> {f.note} {f.sources.map((x) => `${x.label}: ${x.value}`).join(" · ")}</li>)}</ul>
        </div>
      )}

      {plan.providers && (
        <div className="plan-providers" id="plan-providers">
          <h3>🏷️ Mevcut sağlayıcı / rakip sinyalleri</h3>
          <ul className="small">
            {plan.providers.items.map((p) => (
              <li key={p.key} data-provider={p.key}>
                <strong>{p.title}:</strong> <span className={p.status === "dogrulanamadi" ? "unverified" : ""}>{p.value ? `${p.value} — ` : ""}{p.status_label}</span>
                {p.evidence && <div className="muted">{p.evidence}{p.source ? ` (Kaynak: ${p.source})` : ""}</div>}
              </li>
            ))}
          </ul>
          {plan.providers.win_opportunities.map((w, i) => <p key={i} className="notice notice-ok small" data-win={w.service}>🏆 {w.text}</p>)}
        </div>
      )}

      {s && (
        <div className="plan-scripts" id="plan-scripts">
          <h3>🗣️ Kişiselleştirilmiş satış metinleri</h3>
          <div className="chips">
            {([["call", "📞 Telefon"], ["whatsapp", "💬 WhatsApp"], ["email", "📧 E-posta"], ["note", "📝 Kısa not"]] as const).map(([k, l]) => (
              <button key={k} className={`chip ${script === k ? "active" : ""}`} data-script-tab={k} onClick={() => setScript(k)}>{l}</button>
            ))}
          </div>
          <pre className="script-box" id="script-text">{scriptText}</pre>
          <div className="actions"><CopyButton text={scriptText} label="📋 Kopyala" /></div>
          <p className="muted small">{s.caveat} Metin dayanağı: {s.basis}.</p>
        </div>
      )}
    </div>
  );
}
