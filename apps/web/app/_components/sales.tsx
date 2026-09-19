"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import type { Business, CrmEntry, CrmState, FollowUpItem, Guide, Opportunity, SalesNote, ScoreInfo, VerifiedField } from "@/lib/types";
import { CRM_STAGES, crmPatch, GUIDE_SECTION_TITLES, OPP_ICONS, OPP_LEVEL_LABELS, SEVERITY_LABELS, CONFIDENCE_LABELS, formatFollowUp, formatIstanbul, formatTL, telUrl, whatsappUrl } from "./labels";
import { CrmSalesSection } from "./sales-ops";
import { patchStoredBusiness } from "./search-store";

export { Modal } from "./modal";
import { Modal } from "./modal";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function CopyButton({ text, label = "📋 Kopyala" }: { text: string; label?: string }) {
  const [done, setDone] = useState<boolean | null>(null);
  return (
    <button
      className="secondary"
      onClick={async () => {
        setDone(await copyText(text));
        setTimeout(() => setDone(null), 2500);
      }}
    >
      {done === null ? label : done ? "✓ Kopyalandı" : "Kopyalanamadı — metni elle seçin"}
    </button>
  );
}

// ---------------------------------------------------------------- çözüm rehberi
export function guideToText(g: Guide): string {
  const s = g.sections;
  const list = (items: string[]) => items.map((x, i) => `${i + 1}. ${x}`).join("\n");
  return [
    `${g.title} — Çözüm Rehberi`,
    `\n${GUIDE_SECTION_TITLES.what}\n${s.what}`,
    `\n${GUIDE_SECTION_TITLES.why}\n${s.why}`,
    `\n${GUIDE_SECTION_TITLES.solution}\n${s.solution}`,
    `\n${GUIDE_SECTION_TITLES.steps}\n${list(s.steps)}`,
    `\n${GUIDE_SECTION_TITLES.pitch}\n${s.pitch}`,
    `\n${GUIDE_SECTION_TITLES.offer}\n${s.offer}`,
    `\n${GUIDE_SECTION_TITLES.questions}\n${s.questions.map((q) => `- ${q}`).join("\n")}`,
    `\n${GUIDE_SECTION_TITLES.verify}\n${s.verify.map((v) => `- ${v}`).join("\n")}`,
  ].join("\n");
}

export function GuideView({ guide }: { guide: Guide }) {
  const s = guide.sections;
  return (
    <div className="guide">
      <p className="muted small">{guide.category} · İlgili hizmetler: {guide.services.join(", ")}</p>
      {guide.business_evidence.length > 0 && (
        <div className="guide-evidence">
          <strong>Bu işletmede analizde tespit edilen:</strong>
          <ul>
            {guide.business_evidence.map((e, i) => (
              <li key={i}>
                <strong>{e.problem}</strong>
                {e.evidence && <div className="small">Kanıt: {e.evidence}</div>}
                <div className="muted small">Önem: {SEVERITY_LABELS[e.severity] ?? e.severity} · Güven: {CONFIDENCE_LABELS[e.confidence] ?? e.confidence}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
      <section><h3>{GUIDE_SECTION_TITLES.what}</h3><p>{s.what}</p></section>
      <section><h3>{GUIDE_SECTION_TITLES.why}</h3><p>{s.why}</p></section>
      <section><h3>{GUIDE_SECTION_TITLES.solution}</h3><p>{s.solution}</p></section>
      <section><h3>{GUIDE_SECTION_TITLES.steps}</h3><ol>{s.steps.map((x, i) => <li key={i}>{x}</li>)}</ol></section>
      <section className="note"><h3>{GUIDE_SECTION_TITLES.pitch}</h3><p>“{s.pitch}”</p></section>
      <section><h3>{GUIDE_SECTION_TITLES.offer}</h3><p><strong>{s.offer}</strong></p><p className="muted small">İlgili hizmetler: {guide.services.join(" · ")}</p></section>
      <section><h3>{GUIDE_SECTION_TITLES.questions}</h3><ul>{s.questions.map((x, i) => <li key={i}>{x}</li>)}</ul></section>
      <section><h3>{GUIDE_SECTION_TITLES.verify}</h3><ul>{s.verify.map((x, i) => <li key={i}>{x}</li>)}</ul></section>
      <div className="guide-actions"><CopyButton text={guideToText(guide)} label="📋 Rehberi kopyala" /></div>
    </div>
  );
}

export function GuideModal({ guideId, businessId, sectorId, onClose }: { guideId: string; businessId?: number; sectorId?: number; onClose: () => void }) {
  const [guide, setGuide] = useState<Guide | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.getGuide(guideId, { business_id: businessId, sector_id: sectorId }).then(setGuide).catch((e) => setError(e.message));
  }, [guideId, businessId, sectorId]);
  return (
    <Modal title={guide ? `💡 Nasıl Çözülür? — ${guide.title}` : "💡 Nasıl Çözülür?"} onClose={onClose}>
      {error && <p className="error">{error}</p>}
      {!guide && !error && <p className="muted">Rehber yükleniyor…</p>}
      {guide && <GuideView guide={guide} />}
    </Modal>
  );
}

const GuideScope = createContext<{ businessId?: number; sectorId?: number }>({});
export const GuideScopeProvider = GuideScope.Provider;

/** "💡 Nasıl Çözülür?" butonu: bulunduğu işletme bağlamında rehberi açar. guideId yoksa hiçbir şey göstermez. */
export function GuideButton({ guideId, label = "💡 Nasıl Çözülür?" }: { guideId: string | null | undefined; label?: string }) {
  const scope = useContext(GuideScope);
  const [open, setOpen] = useState(false);
  if (!guideId) return null;
  return (
    <>
      <button className="guide-btn" onClick={() => setOpen(true)}>{label}</button>
      {open && <GuideModal guideId={guideId} businessId={scope.businessId} sectorId={scope.sectorId} onClose={() => setOpen(false)} />}
    </>
  );
}

// ---------------------------------------------------------------- satış notu
export function SalesNoteModal({ businessId, onClose, onAppendToNote }: { businessId: number; onClose: () => void; onAppendToNote?: (text: string) => void }) {
  const [note, setNote] = useState<SalesNote | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.getSalesNote(businessId).then(setNote).catch((e) => setError(e.message));
  }, [businessId]);
  return (
    <Modal title="✍️ Satış Notu" onClose={onClose}>
      {error && <p className="error">{error}</p>}
      {!note && !error && <p className="muted">Not hazırlanıyor…</p>}
      {note && (
        <div className="guide">
          <p className="muted small">Bu not yalnızca işletmenin gerçek analiz sonuçlarından üretildi; doğrulanamayan bilgiler ayrıca belirtilir.</p>
          <section>
            <h3>Tespit edilen problem</h3>
            {note.problems.length === 0 ? <p>Somut bir eksik tespit edilmedi.</p> : (
              <ul>{note.problems.map((p, i) => <li key={i}><strong>{p.problem}</strong>{!p.verified && <span className="verify-note small"> (doğrulama gerekli)</span>}{p.evidence && <div className="small muted">{p.evidence}</div>}</li>)}</ul>
            )}
          </section>
          <section>
            <h3>Önerilen hizmet</h3>
            <p>{note.primary_service ? <><strong>{note.primary_service}</strong>{note.secondary_service && <> · ikinci: {note.secondary_service}</>}</> : "Kanıta dayalı bir hizmet önerisi yok."}</p>
            {note.why_service && <p className="small"><strong>Neden bu hizmet:</strong> {note.why_service}</p>}
          </section>
          {note.pitch && <section className="note"><h3>Müşteriye söylenebilecek kısa açıklama</h3><p>“{note.pitch}”</p></section>}
          {note.talking_point && <section><h3>Görüşmeye nasıl başlanır?</h3><p>{note.talking_point}</p></section>}
          {note.questions.length > 0 && <section><h3>Görüşmede sorulabilecek sorular</h3><ul>{note.questions.map((q, i) => <li key={i}>{q}</li>)}</ul></section>}
          {note.caveats.length > 0 && <section><h3>Görüşmeden önce kontrol edin</h3><ul>{note.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul></section>}
          <div className="guide-actions">
            <CopyButton text={note.text} label="📋 Notu kopyala" />
            {onAppendToNote && <button className="secondary" onClick={() => { onAppendToNote(note.text); onClose(); }}>➕ Personel notuna ekle</button>}
          </div>
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------- satış puanı
export function ScoreBlock({ score }: { score: ScoreInfo }) {
  const pct = Math.max(0, Math.min(100, score.score));
  const tone = pct >= 45 ? "score-high" : pct >= 20 ? "score-mid" : "score-low";
  return (
    <div className="card">
      <div className="score-head">
        <div>
          <div className="label-cap">Satış fırsatı puanı</div>
          <div className={`score-number ${tone}`}>{score.score}<span className="score-max"> / 100</span></div>
          <div className="muted small">{score.band}</div>
        </div>
        <div className="score-bar" aria-hidden><div className={`score-bar-fill ${tone}`} style={{ width: `${pct}%` }} /></div>
      </div>
      <h3 style={{ marginTop: 14 }}>Neden bu puanı aldı?</h3>
      <p className="small">{score.summary}</p>
      {score.groups && score.groups.length > 0 && (
        <ul className="score-groups" data-testid="score-groups">
          {score.groups.map((g) => <li key={g.label}><strong>+{g.points}</strong> {g.label}</li>)}
        </ul>
      )}
      {score.items.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Tespit</th><th>Alan</th><th style={{ width: 70 }}>Puan</th><th>Ağırlık nedeni</th></tr></thead>
            <tbody>
              {score.items.map((i, k) => (
                <tr key={k}><td>{i.label}</td><td>{i.area_label}</td><td><strong>+{i.points}</strong></td><td className="muted small">{i.explanation}</td></tr>
              ))}
              {score.adjustments.map((a, k) => (
                <tr key={`a${k}`}><td colSpan={2} className="muted small">{a.label}</td><td><strong>{a.points}</strong></td><td className="muted small">
                    {a.label.includes("varsayım")
                      ? "Doğrulanmamış sektörel varsayımların toplam etkisini sınırlar."
                      : "Bir alandaki çok sayıda bulgunun puanı şişirmesini önler."}
                  </td></tr>
              ))}
              {score.assumptions.map((a, k) => (
                <tr key={`s${k}`} className="row-assumption"><td>{a.label}</td><td>Sektörel varsayım</td><td><strong>+{a.points}</strong></td><td className="muted small">{a.explanation}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">{score.note}</p>
    </div>
  );
}

// ---------------------------------------------------------------- Mchttasarım satış fırsatları
function OpportunityCard({ opp }: { opp: Opportunity }) {
  const icon = OPP_ICONS[opp.level] ?? "⚪";
  return (
    <div className={`card opp ${opp.verified ? "" : "opp-possible"}`}>
      <p className="opp-title">{icon} <strong>{opp.service}</strong> — {OPP_LEVEL_LABELS[opp.level] ?? opp.level}</p>
      {opp.verified ? (
        <div className="opp-problems">
          <strong>Tespit edilen sorun{opp.problems.length > 1 ? "lar" : ""}:</strong>
          <ul>
            {opp.problems.map((p, i) => (
              <li key={i}>
                {p.label}
                {p.needs_verification && <span className="verify-note small"> (doğrulama gerekli)</span>}
                {p.evidence && <div className="muted small">Kanıt: {p.evidence}</div>}
                <GuideButton guideId={p.guide_id} />
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p><strong>Sorun:</strong> <span className="unverified">{opp.problem_text ?? "Tespit edilmedi."}</span></p>
      )}
      <p className="small"><strong>Neden öneriliyor:</strong> {opp.why || "—"}</p>
      <p className="small"><strong>Satış gerekçesi:</strong> {opp.rationale}</p>
      <p className="small"><strong>Sunulabilecek hizmet:</strong> {opp.offer}</p>
      {!opp.verified && <GuideButton guideId={opp.guide_id} label="💡 Rehberi aç" />}
    </div>
  );
}

export function OpportunitySection({ evidence, possible }: { evidence: Opportunity[]; possible: Opportunity[] }) {
  return (
    <section>
      <h2>Mchttasarım Satış Fırsatları</h2>
      <h3>Tespite dayalı fırsatlar</h3>
      {evidence.length === 0 ? (
        <p className="muted">Bu işletmede ölçülen alanlarda Mchttasarım hizmetine bağlanabilecek somut bir eksik tespit edilmedi.</p>
      ) : evidence.map((o) => <OpportunityCard key={o.service} opp={o} />)}
      {possible.length > 0 && (
        <>
          <h3>Sektöre dayalı olası fırsatlar — DOĞRULANMADI</h3>
          <p className="muted small">Bunlar analizde tespit edilmiş sorunlar değil, sektörün doğasından çıkan olası ihtiyaçlardır. Puana yalnızca çok küçük, ayrıca etiketlenmiş bir katkı verirler; görüşmede sorularak doğrulanmalıdır.</p>
          <div className="opp-grid">{possible.map((o) => <OpportunityCard key={o.service} opp={o} />)}</div>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- analiz durumu (rozet)
/**
 * Analiz durumu KULLANICI BAZLIDIR: "Daha önce analiz edildi" yalnızca bakan kullanıcının bu işletme için kendi başarılı analizi varsa görünür.
 * Başka bir kullanıcının analizi ya da işletmenin sistemde bulunması bunu doğurmaz. Tarih ve saat Europe/Istanbul'a göredir.
 */
export function AnalysisBadge({ business, showFresh = true }: { business: Pick<Business, "previously_analyzed" | "analyzed_by_me" | "analyzed_by_me_at" | "analyzed_by_others" | "last_analysis_at">; showFresh?: boolean }) {
  if (business.analyzed_by_me && business.analyzed_by_me_at) {
    const label = !business.previously_analyzed && showFresh ? "Analiz edildi" : "Daha önce analiz edildi";
    return (
      <span className="analysis-badge analysis-done" title="Sizin analiziniz: tamamlandığı gerçek tarih ve saat (Europe/Istanbul)">
        🟢 {label}<span className="analysis-when">{formatIstanbul(business.analyzed_by_me_at)}</span>
      </span>
    );
  }
  if (business.analyzed_by_others && business.last_analysis_at) {
    return (
      <span className="analysis-badge analysis-none" title="Sistemde başka bir kullanıcının analizi var; sizin analiziniz yok. Analiz Et ile kendi analizinizi başlatabilirsiniz.">
        ⚪ Sizin analiziniz yok<span className="analysis-when">sistemde {formatIstanbul(business.last_analysis_at)} tarihli analiz var</span>
      </span>
    );
  }
  return <span className="analysis-badge analysis-none">⚪ Henüz analiz edilmedi</span>;
}

// ---------------------------------------------------------------- CRM
export function CrmBadge({ business }: { business: Pick<Business, "in_crm" | "crm_stage"> }) {
  if (!business.in_crm) return null;
  return <span className="crm-badge" title="Bu firma CRM'de">📋 {business.crm_stage}</span>;
}

/** "➕ CRM'e Ekle" penceresi: durum + not seç, kaydet → firma anında CRM'e düşer. */
export function AddToCrmModal({ business, initialNote, onClose, onAdded }: {
  business: Pick<Business, "id" | "name">;
  initialNote?: string;
  onClose: () => void;
  onAdded: (state: CrmState) => void;
}) {
  const [stage, setStage] = useState<string>("Aranacak");
  const [note, setNote] = useState(initialNote ?? "");
  const [followUp, setFollowUp] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const closing = stage === "Kazanıldı" || stage === "Kaybedildi";

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const state = await api.addToCrm(business.id, { stage, note: note.trim() || undefined, ...(followUp && !closing ? { follow_up_at: followUp } : {}) });
      patchStoredBusiness(business.id, crmPatch(state));
      onAdded(state);
      onClose();
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  }

  return (
    <Modal title="➕ CRM'e Ekle" onClose={onClose}>
      <p><strong>{business.name}</strong></p>
      <div className="form-field" style={{ marginBottom: 10 }}>
        <label htmlFor={`add-crm-stage-${business.id}`}>CRM durumu seç</label>
        <select id={`add-crm-stage-${business.id}`} value={stage} onChange={(e) => setStage(e.target.value)}>
          {CRM_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      {!closing && (
        <div className="form-field" style={{ marginBottom: 10 }}>
          <label htmlFor={`add-crm-follow-${business.id}`}>Takip tarihi (isteğe bağlı)</label>
          <input id={`add-crm-follow-${business.id}`} type="date" value={followUp} onChange={(e) => setFollowUp(e.target.value)} />
        </div>
      )}
      <div className="form-field" style={{ marginBottom: 10 }}>
        <label htmlFor={`add-crm-note-${business.id}`}>Not (isteğe bağlı)</label>
        <textarea id={`add-crm-note-${business.id}`} rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Örn. İlk arama Pazartesi yapılacak." />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="guide-actions">
        <button className="primary" onClick={save} disabled={saving}>{saving ? "Kaydediliyor…" : "Kaydet"}</button>
        <button className="secondary" onClick={onClose}>Vazgeç</button>
      </div>
    </Modal>
  );
}

/** Listede/kartta: CRM'de değilse "➕ CRM'e Ekle" düğmesi (pencere açar); CRM'deyse durum rozeti. `asButton`: kart eylem satırındaki "📋 CRM" düğmesi. */
export function CrmCardControl({ business, onChanged, asButton = false }: { business: Business; onChanged: (state: CrmState) => void; asButton?: boolean }) {
  const [open, setOpen] = useState(false);
  if (business.in_crm) {
    return asButton
      ? <a className="qa-btn crm-in" href={`/businesses/${business.id}#crm-panel`}>📋 CRM: {business.crm_stage}</a>
      : <CrmBadge business={business} />;
  }
  return (
    <>
      <button className={asButton ? "qa-btn" : "crm-add-btn"} onClick={() => setOpen(true)}>{asButton ? "📋 CRM'e Ekle" : "➕ CRM'e Ekle"}</button>
      {open && <AddToCrmModal business={business} onClose={() => setOpen(false)} onAdded={onChanged} />}
    </>
  );
}

const META_LABELS: Record<string, string> = { offer_amount: "Teklif tutarı", sale_amount: "Satış tutarı", lost_reason: "Kaybedilme nedeni", interested_service: "İlgilenilen hizmet", follow_up_at: "Takip tarihi", follow_up_note: "Takip notu", owner_id: "Sorumlu" };

/** Geçmiş kaydındaki satış alanı değişiklikleri (yalnızca gerçekten değişenler kayıtlıdır). */
function HistoryMeta({ meta }: { meta: Record<string, unknown> }) {
  const parts = Object.entries(meta).filter(([k]) => META_LABELS[k]).map(([k, v]) => {
    const text = v === null || v === undefined || v === "" ? "temizlendi" : k.endsWith("_amount") ? formatTL(Number(v)) : k === "follow_up_at" ? formatFollowUp(String(v)) : k === "owner_id" ? `#${v}` : String(v);
    return `${META_LABELS[k]}: ${text}`;
  });
  return parts.length ? <div className="small muted crm-h-meta">{parts.join(" · ")}</div> : null;
}

/** Firma detayında: "📋 CRM Durumu / CRM Bilgileri" + not düzenleme + "🕘 CRM İşlem Geçmişi". */
export function CrmPanel({ business, history, noteToAppend, onUpdated, followUps, onReload }: {
  business: Business;
  history: CrmEntry[];
  noteToAppend?: string;
  onUpdated: (state: CrmState) => void;
  followUps?: FollowUpItem[];
  onReload?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(business.staff_note ?? "");
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { if (!editing) setNote(business.staff_note ?? ""); }, [business.staff_note, editing]);
  // "Personel notuna ekle": CRM'deyse not düzenleyicide açılır; CRM'de değilse "CRM'e Ekle" penceresinde hazır gelir.
  useEffect(() => {
    if (!noteToAppend) return;
    if (business.in_crm) { setEditing(true); setNote((prev) => (prev ? `${prev}\n\n${noteToAppend}` : noteToAppend)); }
    else setAdding(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteToAppend]);

  async function apply(body: { stage?: string; staff_note?: string }, okText: string) {
    setSaving(true);
    setMessage(null);
    try {
      const state = await api.updateCrm(business.id, body);
      patchStoredBusiness(business.id, crmPatch(state));
      onUpdated(state);
      setMessage({ ok: true, text: okText });
      setEditing(false);
    } catch (e) {
      setMessage({ ok: false, text: `Kaydedilemedi: ${(e as Error).message}` });
    } finally {
      setSaving(false);
    }
  }

  if (!business.in_crm) {
    return (
      <div className="card crm-card" id="crm-panel">
        <h2 style={{ marginTop: 0 }}>📋 CRM Durumu</h2>
        <p className="muted">Bu firma henüz CRM&apos;de değil. Analiz edilmiş olması firmayı CRM&apos;e otomatik eklemez; eklemek isterseniz aşağıdaki düğmeyi kullanın.</p>
        <button className="primary" onClick={() => setAdding(true)}>➕ CRM&apos;e Ekle</button>
        {message && <p className={message.ok ? "small" : "error"}>{message.text}</p>}
        {adding && <AddToCrmModal business={business} initialNote={noteToAppend} onClose={() => setAdding(false)} onAdded={(state) => { onUpdated(state); setMessage({ ok: true, text: "✓ Firma CRM'e eklendi." }); }} />}
      </div>
    );
  }

  return (
    <div className="card crm-card" id="crm-panel">
      <h2 style={{ marginTop: 0 }}>📋 CRM BİLGİLERİ</h2>
      <div className="crm-grid">
        <div className="form-field">
          <label htmlFor="crm-stage">CRM Durumu</label>
          <select id="crm-stage" value={business.crm_stage} disabled={saving} onChange={(e) => apply({ stage: e.target.value }, `✓ Durum “${e.target.value}” olarak kaydedildi.`)}>
            {CRM_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <div className="label-cap">Son İşlem</div>
          <div id="crm-last-action">{formatIstanbul(business.crm_updated_at ?? business.crm_added_at)}</div>
        </div>
        <div>
          <div className="label-cap">CRM&apos;e Eklenme</div>
          <div>{formatIstanbul(business.crm_added_at)}</div>
          <div className="small muted" id="crm-added-by">Ekleyen: {business.crm_added_by_name ?? "—"}</div>
        </div>
        <div>
          <div className="label-cap">Son İşlemi Yapan</div>
          <div id="crm-updated-by">{business.crm_updated_by_name ?? "—"}</div>
          {business.crm_last_action && <div className="small muted" id="crm-last-action-text">{business.crm_last_action}</div>}
        </div>
      </div>

      <div style={{ marginTop: 12 }}>
        <div className="label-cap">CRM Notu</div>
        {!editing && (
          <>
            <p id="crm-note-view" style={{ whiteSpace: "pre-wrap", margin: "4px 0" }}>{business.staff_note || <span className="muted">Henüz not yok.</span>}</p>
            <button className="secondary" onClick={() => { setNote(business.staff_note ?? ""); setEditing(true); setMessage(null); }}>✏️ CRM Notu Ekle/Düzenle</button>
          </>
        )}
        {editing && (
          <>
            <label className="sr-only" htmlFor="staff-note">CRM notu</label>
            <textarea id="staff-note" rows={4} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Görüşme notlarınızı buraya yazın…" />
            <div className="actions" style={{ marginTop: 8 }}>
              <button className="primary" disabled={saving} onClick={() => apply({ staff_note: note }, "✓ Not kaydedildi.")}>{saving ? "Kaydediliyor…" : "Notu Kaydet"}</button>
              <button className="secondary" disabled={saving} onClick={() => { setEditing(false); setNote(business.staff_note ?? ""); }}>Vazgeç</button>
            </div>
          </>
        )}
      </div>
      {message && <p role="status" className={message.ok ? "small crm-ok" : "error"}>{message.text}</p>}

      <CrmSalesSection business={business} onUpdated={onUpdated} followUps={followUps} onReload={onReload} />

      <h3 style={{ marginTop: 18 }}>🕘 CRM İşlem Geçmişi</h3>
      {history.length === 0 ? <p className="muted small">Henüz işlem kaydı yok.</p> : (
        <ol className="crm-history" id="crm-history">
          {history.map((h, i) => (
            <li key={h.id ?? i}>
              <div className="crm-h-when">{formatIstanbul(h.created_at)} · <strong className="crm-h-user">{h.user_name ?? "Bilinmiyor (eski kayıt)"}</strong></div>
              <div className="crm-h-stage">
                {h.type === "status_change" && h.from_stage ? <>{h.from_stage} → <strong>{h.to_stage}</strong></> : <strong>{h.to_stage ?? "—"}</strong>}
                {h.type === "added" && <span className="muted small"> · CRM&apos;e eklendi</span>}
                {h.type === "note" && <span className="muted small"> · not güncellendi</span>}
                {h.type === "contact" && <span className="muted small"> · iletişim</span>}
                {h.type === "follow_up" && <span className="muted small"> · takip</span>}
                {h.type === "follow_up_done" && <span className="muted small"> · takip tamamlandı</span>}
                {h.type === "sales_update" && <span className="muted small"> · satış bilgileri</span>}
              </div>
              {h.note && <div className="small crm-h-note">{h.type === "contact" || h.type === "follow_up" || h.type === "follow_up_done" || h.type === "sales_update" ? h.note : `Not: ${h.note}`}</div>}
              {h.meta && <HistoryMeta meta={h.meta} />}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- hızlı aksiyonlar
export function QuickActions({ business, website, onSalesNote, onGuides, onAddToCrm, canSalesNote = true }: {
  business: Business;
  canSalesNote?: boolean;
  website: VerifiedField | undefined;
  onSalesNote: () => void;
  onGuides: () => void;
  onAddToCrm: () => void;
}) {
  const tel = telUrl(business.phone);
  const wa = whatsappUrl(business.phone);
  const verifiedSite = website?.status === "dogrulandi" && website.value ? website.value : null;
  return (
    <div className="quick-actions" role="toolbar" aria-label="Hızlı aksiyonlar">
      {tel && <a className="qa-btn" href={tel}>📞 Ara</a>}
      {wa && <a className="qa-btn" href={wa} target="_blank" rel="noreferrer">💬 WhatsApp</a>}
      <a className="qa-btn" href={business.maps_url ?? business.maps_search_url} target="_blank" rel="noreferrer">
        📍 {business.maps_url ? "Google Maps" : "Haritalarda ara"}
      </a>
      {verifiedSite ? (
        <a className="qa-btn" href={verifiedSite} target="_blank" rel="noreferrer">🌐 Web Sitesi</a>
      ) : (
        <span className="qa-btn qa-disabled" title={business.website ? `Doğrulanmamış adres: ${business.website}` : "Doğrulanmış web sitesi bulunamadı"}>
          🌐 {business.website ? "Web sitesi doğrulanmadı" : "Web sitesi bulunamadı"}
        </span>
      )}
      {canSalesNote && <button className="qa-btn" onClick={onSalesNote} disabled={business.sales_level === null}>✍️ Satış Notu</button>}
      <button className="qa-btn" onClick={onGuides} disabled={business.sales_level === null}>💡 Nasıl Çözülür?</button>
      <button className="qa-btn" onClick={onAddToCrm}>{business.in_crm ? "📋 CRM Durumu" : "➕ CRM'e Ekle"}</button>
    </div>
  );
}
