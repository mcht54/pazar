"use client";

import { GuideButton } from "./sales";
import type { Assessment, Business, Check, QuickRow, SocialAccount, SourceStatusItem, VerifiedField } from "@/lib/types";
import {
  CHECK_STATUS_LABELS,
  CONFIDENCE_LABELS,
  FIELD_ORDER,
  SEVERITY_LABELS,
  SOURCE_STATE_LABELS,
  UNVERIFIED,
  VERIFY_HELP,
  VERIFY_LABELS,
  formatDateTime,
  levelClass,
} from "./labels";

export function Unverified({ text = UNVERIFIED }: { text?: string }) {
  return <span className="unverified">{text}</span>;
}

/** Değer yoksa "Doğrulanamadı" gösterir — asla boş/tahmini değer basmaz. */
export function Val({ children }: { children: React.ReactNode | null | undefined }) {
  if (children === null || children === undefined || children === "") return <Unverified />;
  return <>{children}</>;
}

export function LevelBadge({ level }: { level: string | null }) {
  if (!level) return <span className="level level-pending">Analiz bekliyor</span>;
  return <span className={`level ${levelClass(level)}`}>{level}</span>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`badge sev-${severity}`}>{SEVERITY_LABELS[severity] ?? severity}</span>;
}

export function CheckStatus({ check }: { check: Check }) {
  return <span className={`badge status-${check.status}`}>{CHECK_STATUS_LABELS[check.status]}</span>;
}

export function ChecksTable({ checks, empty }: { checks: Check[]; empty?: string }) {
  if (checks.length === 0) return <p className="muted">{empty ?? "Kontrol sonucu yok."}</p>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th style={{ width: "22%" }}>Kontrol</th>
            <th style={{ width: "12%" }}>Durum</th>
            <th>Sonuç ve kanıt</th>
            <th style={{ width: "30%" }}>Neden önemli / Mchttasarım burada ne satabilir?</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((c) => (
            <tr key={`${c.area}-${c.key}`} className={c.status === "problem" ? "row-problem" : undefined}>
              <td><strong>{c.label}</strong></td>
              <td>
                <CheckStatus check={c} />
                {c.status === "problem" && (
                  <div className="muted small">Önem: {SEVERITY_LABELS[c.severity]} · Güven: {CONFIDENCE_LABELS[c.confidence]}</div>
                )}
              </td>
              <td>
                {c.status === "unknown" ? <Unverified text={c.value} /> : c.value}
                {c.detail && <div className="muted small">{c.detail}</div>}
                {c.needs_verification && <div className="verify-note small">Doğrulama gerekli</div>}
              </td>
              <td>
                {c.status === "problem" ? (
                  <>
                    {c.why && <div className="small">{c.why}</div>}
                    {c.services.length > 0 && (
                      <div className="small"><strong>Satılabilecek hizmet:</strong> {c.services.join(", ")}</div>
                    )}
                    <GuideButton guideId={c.guide_id} />
                  </>
                ) : (
                  <span className="muted small">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Kart ve detay sayfasında ortak kullanılan tam analiz bölümleri. */
export function AnalysisSections({ business, assessment }: { business: Business; assessment: Assessment }) {
  const gbp = assessment.gbp;
  const web = assessment.website;
  const gbpProblems = gbp.checks.filter((c) => c.status === "problem");
  const webProblems = web.checks.filter((c) => c.status === "problem");

  return (
    <div className="analysis">
      <section>
        <h3>Google İşletme Analizi</h3>
        <p className="muted small">
          Kaynak: {gbp.source_label ?? UNVERIFIED} · Kontrol zamanı: {formatDateTime(gbp.checked_at)}
          {" · "}
          <a href={gbp.maps_url ?? gbp.maps_search_url ?? business.maps_search_url} target="_blank" rel="noreferrer">
            {gbp.maps_url ? "Google Haritalar'da aç" : "Google Haritalar'da ara (doğrulama için)"}
          </a>
        </p>
        <p>{gbp.status_text}</p>
        {gbp.available && gbpProblems.length > 0 && (
          <p><strong>Google Haritalar görünürlüğünü etkileyebilecek eksikler:</strong> {gbpProblems.map((c) => c.value).join(" · ")}</p>
        )}
        <ChecksTable checks={gbp.checks} />
      </section>

      <section>
        <h3>Web Sitesi Analizi</h3>
        <p className="muted small">
          {web.url ? <>Adres: <a href={web.final_url ?? web.url} target="_blank" rel="noreferrer">{web.final_url ?? web.url}</a></> : "Web sitesi adresi bulunamadı"}
          {" · "}Kontrol zamanı: {formatDateTime(web.checked_at)}
          {web.response_ms ? <> · Yanıt süresi: {(web.response_ms / 1000).toFixed(1)} sn</> : null}
        </p>
        <p>{web.status_text}</p>
        {web.analyzed && webProblems.length === 0 && <p>Ölçülen alanlarda somut bir eksik tespit edilmedi.</p>}
        {web.pagespeed_note && <p className="muted small">Google PageSpeed (mobil) ölçümü: {UNVERIFIED} — {web.pagespeed_note}. Sayfa hızı için kendi ölçümümüz (yaklaşık) kullanıldı.</p>}
        <ChecksTable checks={web.checks} />
      </section>
    </div>
  );
}


// ---------------------------------------------------------------- veri doğrulama
export function VerifyBadge({ field }: { field: VerifiedField }) {
  const label = VERIFY_LABELS[field.status] ?? field.status;
  return <span className={`vbadge v-${field.status}`} title={VERIFY_HELP[field.status]}>{label}</span>;
}

/** Bir bilginin değeri + doğrulama durumu + kaynakları. */
export function VerifiedValue({ field, fallback }: { field: VerifiedField | undefined; fallback?: string }) {
  if (!field) return <Unverified text={fallback ?? "Araştırma yapılmadı"} />;
  return (
    <div className="vv">
      <div>
        {field.value ? <span className="vv-value">{field.value}</span> : <span className="unverified">{field.checked ? "Bulunamadı" : "Kontrol edilemedi"}</span>}
        {" "}<VerifyBadge field={field} />
      </div>
      {field.sources.length > 0 && <div className="muted small">Kaynak: {field.sources.map((s) => s.label).join(" + ")}</div>}
      {!field.checked && field.status === "bulunamadi" && <div className="muted small">Google İşletme Profili erişilemediği/eşleşmediği için kontrol edilemedi.</div>}
      {field.note && <div className="muted small">{field.note}</div>}
    </div>
  );
}

export function SourceStatusPanel({ statuses }: { statuses: SourceStatusItem[] }) {
  if (statuses.length === 0) return <p className="muted small">Bu işletme için henüz çok kaynaklı araştırma yapılmadı.</p>;
  return (
    <ul className="source-list">
      {statuses.map((s) => (
        <li key={s.key} title={s.detail}>
          <span className="source-name">{s.label}:</span>{" "}
          <span className={`sbadge s-${s.status}`}>{SOURCE_STATE_LABELS[s.status] ?? s.status}</span>
          {s.detail && <div className="muted small">{s.detail}</div>}
        </li>
      ))}
    </ul>
  );
}

export function VerificationBlock({ verification }: { verification: Record<string, VerifiedField> }) {
  const fields = FIELD_ORDER.map((k) => verification[k]).filter(Boolean);
  if (fields.length === 0) return <p className="muted small">Doğrulama verisi yok (araştırma yapılmadı).</p>;
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th style={{ width: "22%" }}>Bilgi</th><th>Değer ve doğrulama</th></tr></thead>
        <tbody>
          {fields.map((f) => (
            <tr key={f.key}><td><strong>{f.label}</strong></td><td><VerifiedValue field={f} /></td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SocialBlock({ accounts }: { accounts: SocialAccount[] }) {
  if (accounts.length === 0) return null;
  return (
    <ul className="social-list">
      {accounts.map((a) => (
        <li key={a.network}>
          <strong>{a.label}:</strong>{" "}
          {a.url ? <a href={a.url} target="_blank" rel="noreferrer">{a.url}</a> : <span className="unverified">Bulunamadı</span>}{" "}
          <span className={`vbadge v-${a.status}`}>{VERIFY_LABELS[a.status]}</span>
          <div className="muted small">{a.sources.length > 0 ? `Kaynak: ${a.sources.join(" + ")}. ` : ""}{a.note}</div>
        </li>
      ))}
    </ul>
  );
}

export function QuickList({ rows }: { rows: QuickRow[] }) {
  if (rows.length === 0) return <p className="muted small">Ölçüm yok.</p>;
  return (
    <ul className="quick">
      {rows.map((r) => (
        <li key={r.label} title={r.value}>
          <span className="quick-label">{r.label}:</span> <span className={`state st-${r.state === "DOĞRULANAMADI" ? "unk" : r.state.toLowerCase()}`}>{r.state}</span>
        </li>
      ))}
    </ul>
  );
}
