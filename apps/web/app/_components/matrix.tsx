"use client";

import type { Business, MatrixItem, PriorityInfo, ServiceMatrix } from "@/lib/types";
import { CONFIDENCE_LABELS, SEVERITY_LABELS, formatIstanbul } from "./labels";
import { GuideButton } from "./sales";

const LEVEL_ICON: Record<string, string> = { satis: "🟢", olasi: "🟡", zayif: "⚪", uygun_degil: "🔴" };
const LEVEL_TEXT: Record<string, string> = { satis: "Satış fırsatı", olasi: "Olası fırsat", zayif: "Zayıf fırsat", uygun_degil: "Uygun değil" };

/** ⏳ Analiz ediliyor · ✅ Analiz tamamlandı · ⚠️ Kısmen analiz edildi · ❌ Analiz başarısız · ⚪ Henüz analiz edilmedi */
export function AnalysisStateBadge({ business }: { business: Pick<Business, "analysis_state" | "analysis_state_label"> }) {
  const icon = { running: "⏳", completed: "✅", partial: "⚠️", failed: "❌", none: "⚪" }[business.analysis_state] ?? "⚪";
  return <span className={`state-badge state-${business.analysis_state}`} data-state={business.analysis_state}>{icon} {business.analysis_state_label}</span>;
}

/** 🔥 Neden Potansiyel Müşteri? — yalnızca gerçek analiz bulguları (kanıtsız sektör olasılıkları burada yer almaz). */
export function WhyProspect({ items, compact = false }: { items: string[]; compact?: boolean }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="why-prospect" data-testid="why-prospect">
      <div className="label-cap">🔥 Neden Potansiyel Müşteri?</div>
      <ul>{(compact ? items.slice(0, 4) : items).map((t, i) => <li key={i}>{t}</li>)}</ul>
    </div>
  );
}

/** Neden bu sırada? — öncelik puanı bileşenleri ve gerekçeleri. */
export function PriorityBlock({ priority }: { priority: PriorityInfo }) {
  const labels: Record<string, string> = { score: "Satış fırsatı skoru", opportunity_count: "Fırsat sayısı", commercial: "Ticari anlamlılık", completeness: "Analiz tamamlanma" };
  return (
    <div className="card" id="priority-block">
      <h3 style={{ marginTop: 0 }}>📈 Neden bu sırada? <span className="score-pill score-high" style={{ marginLeft: 8 }}>Öncelik {priority.value}/100</span></h3>
      <p className="muted small">Sıralama yalnızca skora bakmaz: skor, tespit edilen satılabilir hizmet sayısı, hizmetlerin ticari anlamlılığı ve analizin tamamlanma durumu birlikte değerlendirilir.</p>
      <div className="prio-bars">
        {Object.entries(priority.components).map(([k, v]) => (
          <div key={k} className="prio-row">
            <span className="small">{labels[k] ?? k} <span className="muted">(×{priority.weights[k] ?? ""})</span></span>
            <div className="score-bar" aria-hidden><div className="score-bar-fill score-mid" style={{ width: `${Math.min(100, v)}%` }} /></div>
            <strong className="small">{Math.round(v)}</strong>
          </div>
        ))}
      </div>
      <ul className="small">{priority.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
    </div>
  );
}

function EvidenceList({ item }: { item: MatrixItem }) {
  if (item.evidence.length === 0) return <p className="unverified">Tespit edilmedi — bu, sektörün doğasından çıkan olası bir ihtiyaçtır; görüşmede doğrulanmalı.</p>;
  return (
    <ul className="matrix-evidence">
      {item.evidence.map((e, i) => (
        <li key={i}>
          <strong>{e.text}</strong>{" "}
          {e.verified ? <span className="vbadge v-dogrulandi">Doğrulandı</span> : <span className="vbadge v-tek_kaynak">Doğrulama gerekli</span>}
          {e.detail && <div className="small muted">Kanıt: {e.detail}</div>}
          {e.area !== "derived" && <div className="small muted">Önem: {SEVERITY_LABELS[e.severity] ?? e.severity} · Güven: {CONFIDENCE_LABELS[e.confidence] ?? e.confidence}</div>}
        </li>
      ))}
    </ul>
  );
}

function MatrixCard({ item }: { item: MatrixItem }) {
  return (
    <div className={`card matrix-card matrix-${item.level}`} data-service={item.service} data-level={item.level}>
      <p className="opp-title">{LEVEL_ICON[item.level]} <strong>{item.service}</strong> — {LEVEL_TEXT[item.level]}{item.recurring && <span className="muted small"> · aylık hizmet</span>}</p>
      <p className="small"><strong>Sorun:</strong> {item.problem}</p>
      <div className="small"><strong>Kanıt:</strong><EvidenceList item={item} /></div>
      <p className="small"><strong>Neden satılabilir:</strong> {item.why}</p>
      <p className="small"><strong>Mchttasarım ne yapabilir:</strong> {item.what}</p>
      <p className="small"><strong>Müşteriye nasıl anlatılır:</strong> “{item.pitch}”</p>
      {item.caveat && <p className="small verify-note">⚠ {item.caveat}</p>}
      <GuideButton guideId={item.guide_id} />
    </div>
  );
}

/** 🎯 Mchttasarım Satış Fırsatları — her hizmet tek tek (🟢/🟡/⚪/🔴). */
export function ServiceMatrixSection({ matrix }: { matrix: ServiceMatrix }) {
  const strong = matrix.items.filter((i) => i.level === "satis");
  const possible = matrix.items.filter((i) => i.level === "olasi");
  const weak = matrix.items.filter((i) => i.level === "zayif");
  const none = matrix.items.filter((i) => i.level === "uygun_degil");
  const numbered = [...strong, ...possible.filter((i) => !i.sector_only)];
  return (
    <section id="service-matrix">
      <h2>🎯 Mchttasarım Satış Fırsatları</h2>
      <div className="matrix-counts" data-testid="matrix-counts">
        <span>🟢 Satış fırsatı: <strong>{matrix.counts.satis}</strong></span>
        <span>🟡 Olası: <strong>{matrix.counts.olasi}</strong></span>
        <span>⚪ Zayıf: <strong>{matrix.counts.zayif}</strong></span>
        <span>🔴 Uygun değil: <strong>{matrix.counts.uygun_degil}</strong></span>
      </div>
      <p className="muted small">Her Mchttasarım hizmeti bu firma için tek tek değerlendirildi. Yalnızca gerçek analiz bulgularına dayanan hizmetler 🟢 olur; kanıtı olmayan sektörel ihtiyaçlar en fazla 🟡'dir ve görüşmede doğrulanmalıdır.</p>
      {numbered.length > 0 && (
        <div className="card" id="matrix-summary">
          <ol className="matrix-list">
            {numbered.map((i) => (
              <li key={i.service}><strong>{i.service}</strong> <span className="muted small">{LEVEL_ICON[i.level]}</span><div className="small">Neden: {i.evidence[0]?.text ?? i.problem}</div></li>
            ))}
          </ol>
        </div>
      )}
      {strong.length === 0 && possible.length === 0 && <p className="muted">Bu firmada gerçek bulguya dayanan veya olası bir hizmet fırsatı tespit edilmedi.</p>}
      {strong.map((i) => <MatrixCard key={i.service} item={i} />)}
      {possible.map((i) => <MatrixCard key={i.service} item={i} />)}
      {weak.length > 0 && (
        <details className="card compact"><summary>⚪ Zayıf fırsatlar ({weak.length})</summary>
          {weak.map((i) => <MatrixCard key={i.service} item={i} />)}
        </details>
      )}
      {none.length > 0 && (
        <details className="card compact" id="matrix-none"><summary>🔴 Uygun olmayan hizmetler ({none.length})</summary>
          <ul className="small">{none.map((i) => <li key={i.service}><strong>{i.service}:</strong> {i.not_applicable_reason ?? i.problem}</li>)}</ul>
        </details>
      )}
    </section>
  );
}

/** 🕘 Analiz Geçmişi — her analiz ayrı satır: kim, ne zaman, durum. */
export function AnalysisHistory({ items }: { items: { id: number; status: string; trigger: string; user_name: string; completed_at: string | null }[] }) {
  if (items.length === 0) return null;
  const label: Record<string, string> = { completed: "✅ Tamamlandı", partial: "⚠️ Kısmen", failed: "❌ Başarısız", running: "⏳ Sürüyor", pending: "⏳ Sırada" };
  return (
    <div className="card" id="analysis-history">
      <h3 style={{ marginTop: 0 }}>🕘 Analiz Geçmişi</h3>
      <ol className="crm-history">
        {items.map((h) => (
          <li key={h.id}>
            <div className="crm-h-when">{h.completed_at ? formatIstanbul(h.completed_at) : "Sürüyor / tamamlanmadı"}</div>
            <div className="crm-h-stage"><strong>Analiz eden: {h.user_name}</strong> <span className="muted small">· {label[h.status] ?? h.status}</span></div>
          </li>
        ))}
      </ol>
    </div>
  );
}
