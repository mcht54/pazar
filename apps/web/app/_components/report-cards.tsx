"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AnalysisReport, CrmSummary, PeriodStat, ReportPeriod } from "@/lib/types";
import { CRM_DOTS, formatIstanbul } from "./labels";

const ROWS: { key: ReportPeriod; icon: string; label: string; listLabel: string }[] = [
  { key: "today", icon: "📅", label: "Bugün", listLabel: "Bugün Analiz Edilenler" },
  { key: "week", icon: "📆", label: "Bu Hafta", listLabel: "Bu Hafta Analiz Edilenler" },
  { key: "month", icon: "🗓️", label: "Bu Ay", listLabel: "Bu Ay Analiz Edilenler" },
  { key: "total", icon: "📈", label: "Toplam", listLabel: "Şimdiye Kadar Analiz Edilenler" },
];
export const PERIOD_TITLES: Record<ReportPeriod, string> = Object.fromEntries(ROWS.map((r) => [r.key, r.listLabel])) as Record<ReportPeriod, string>;

const nf = new Intl.NumberFormat("tr-TR");

function describe(stat: PeriodStat): string {
  // İki sayı her zaman ayrı gösterilir: başarılı analiz işlemi sayısı · o aralıkta analiz edilen benzersiz firma sayısı.
  return `${nf.format(stat.analyses)} analiz · ${nf.format(stat.businesses)} firma`;
}

/** 📊 ANALİZ RAPORU — gerçek analiz kayıtlarından (tamamlanan analiz işlemleri, Europe/Istanbul). Satıra tıklayınca o dönemin firmaları listelenir. */
export function AnalysisReportCard({ version, active, onSelect }: { version: number; active: ReportPeriod | null; onSelect: (period: ReportPeriod | null) => void }) {
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => api.getAnalysisReport().then((r) => { if (!cancelled) { setReport(r); setError(null); } }).catch((e) => { if (!cancelled) setError(e.message); });
    load();
    const timer = setInterval(load, 30000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [version]);

  return (
    <section className="card side-card" aria-label="Analiz raporu" id="analysis-report">
      <h2>📊 ANALİZ RAPORU</h2>
      {error && <p className="error small">Rapor alınamadı: {error}</p>}
      {!report && !error && <p className="muted small">Yükleniyor…</p>}
      {report && (
        <>
          <ul className="report-list">
            {ROWS.map((row) => {
              const stat = report[row.key];
              return (
                <li key={row.key}>
                  <button
                    className={`report-row ${active === row.key ? "active" : ""}`}
                    data-period={row.key}
                    onClick={() => onSelect(active === row.key ? null : row.key)}
                    title={`${row.listLabel} — tıklayınca firmaları listeler`}
                    aria-pressed={active === row.key}
                  >
                    <span className="report-label">{row.icon} {row.label}</span>
                    <span className="report-count" data-testid={`report-${row.key}`}>{nf.format(stat.analyses)}</span>
                    <span className="report-desc muted small">{describe(stat)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="muted small" style={{ margin: "6px 0 0" }}>
            Yalnızca başarıyla tamamlanan analizler sayılır (kısmi/başarısız analiz, keşif/arama ve bakım yeniden hesaplamaları sayılmaz).
            {report.first_analysis_at && <> İlk analiz kaydı: {formatIstanbul(report.first_analysis_at).slice(0, 10)}.</>}
            <br />Güncelleme: {formatIstanbul(report.updated_at).slice(-5)} · {report.timezone}
          </p>
        </>
      )}
    </section>
  );
}

const SUMMARY_STAGES = ["Aranacak", "Görüşüldü", "Teklif Gönderildi", "Kazanıldı"] as const;

/** 📋 CRM ÖZETİ — gerçek CRM kayıtlarından. */
export function CrmSummaryCard({ version }: { version: number }) {
  const [summary, setSummary] = useState<CrmSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getCrmSummary().then((r) => { if (!cancelled) { setSummary(r); setError(null); } }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [version]);

  const shown = summary ? SUMMARY_STAGES.reduce((sum, s) => sum + (summary.by_stage[s] ?? 0), 0) : 0;
  return (
    <section className="card side-card" aria-label="CRM özeti" id="crm-summary">
      <h2>📋 CRM ÖZETİ</h2>
      {error && <p className="error small">CRM özeti alınamadı: {error}</p>}
      {!summary && !error && <p className="muted small">Yükleniyor…</p>}
      {summary && (
        <>
          <div className="crm-total" data-testid="crm-total"><span>CRM&apos;deki Firmalar</span><strong>{nf.format(summary.total)}</strong></div>
          {summary.total === 0 ? (
            <p className="muted small">Henüz CRM&apos;e alınmış firma yok. Bir firmayı “➕ CRM&apos;e Ekle” ile CRM&apos;e alabilirsiniz.</p>
          ) : (
            <ul className="crm-mini">
              {SUMMARY_STAGES.map((s) => (
                <li key={s}><span>{CRM_DOTS[s]} {s}</span><strong>{nf.format(summary.by_stage[s] ?? 0)}</strong></li>
              ))}
              <li><span>⚪ Diğer</span><strong>{nf.format(summary.total - shown)}</strong></li>
            </ul>
          )}
          <Link className="qa-btn" href="/crm" style={{ marginTop: 8 }}>📋 CRM&apos;i Aç</Link>
        </>
      )}
    </section>
  );
}
