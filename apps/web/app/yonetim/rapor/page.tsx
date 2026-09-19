"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ReportPeriod, RevenueRow, SalesOverview, StaffReport } from "@/lib/types";
import { formatIstanbul, formatTL } from "../../_components/labels";

const PERIODS: { key: ReportPeriod; label: string }[] = [
  { key: "today", label: "Bugün" }, { key: "week", label: "Bu Hafta" }, { key: "month", label: "Bu Ay" }, { key: "total", label: "Toplam" },
];

export default function StaffReportPage() {
  const [period, setPeriod] = useState<ReportPeriod>("today");
  const [data, setData] = useState<StaffReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overview, setOverview] = useState<SalesOverview | null>(null);
  useEffect(() => { api.getSalesOverview(period).then(setOverview).catch((e) => setError(e.message)); }, [period]);
  useEffect(() => { api.getStaffReport(period).then((r) => { setData(r); setError(null); }).catch((e) => setError(e.message)); }, [period]);

  return (
    <div className="container container-wide">
      <header className="page-header">
        <h1>📊 Personel Raporu</h1>
        <p className="lead">Personel bazında analiz, arama (CRM'de "Arandı"), teklif ve kazanılan sayıları — hepsi kullanıcıyla ilişkili gerçek kayıtlardan hesaplanır. Bakım amaçlı otomatik yeniden hesaplamalar analiz sayısına dahil edilmez.</p>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="chips" style={{ marginBottom: 12 }}>
        {PERIODS.map((p) => <button key={p.key} className={`chip ${period === p.key ? "active" : ""}`} onClick={() => setPeriod(p.key)}>{p.label}</button>)}
      </div>
      {data && <p className="muted small">{data.label}{data.since ? ` — ${formatIstanbul(data.since)} tarihinden itibaren (Europe/Istanbul)` : ""}</p>}
      <div className="card table-scroll">
        <table id="staff-report">
          <thead><tr><th>Personel</th><th>Analiz</th><th>Arama (firma)</th><th>CRM'e ekleme</th><th>İletişim</th><th>Teklif</th><th>Kazanılan</th><th>Not</th><th>Dışa aktarma</th><th>Giriş</th></tr></thead>
          <tbody>
            {data?.items.map((r) => (
              <tr key={r.user_id}><td><strong>{r.name}</strong>{!r.is_active && <span className="muted small"> (pasif)</span>}</td><td>{r.analyses}</td><td>{r.searches}</td><td>{r.crm_added}</td><td>{r.calls}</td><td>{r.offers}</td><td>{r.customers}</td><td>{r.notes}</td><td>{r.exports}</td><td>{r.logins}</td></tr>
            ))}
            {!data && <tr><td colSpan={10} className="muted">Yükleniyor…</td></tr>}
          </tbody>
        </table>
      </div>

      {overview && (
        <>
          <h2 style={{ marginTop: 24 }}>💼 Satış Performansı — {overview.label}</h2>
          <div className="card">
            <dl className="crm-facts" id="sales-metrics">
              <div><dt>Analiz</dt><dd data-testid="m-analyses">{overview.metrics.analyses} ({overview.metrics.analyzed_businesses} firma)</dd></div>
              <div><dt>Yeni potansiyel (CRM'e alınan)</dt><dd data-testid="m-leads">{overview.metrics.new_leads}</dd></div>
              <div><dt>İletişim (firma)</dt><dd data-testid="m-contacts">{overview.metrics.contacts}</dd></div>
              <div><dt>İlgilenen</dt><dd data-testid="m-interested">{overview.metrics.interested}</dd></div>
              <div><dt>Gönderilen teklif</dt><dd data-testid="m-offers">{overview.metrics.offers_sent}</dd></div>
              <div><dt>Satış</dt><dd data-testid="m-won">{overview.metrics.won} · {formatTL(overview.metrics.won_total)}{overview.metrics.won_amount_missing ? ` (${overview.metrics.won_amount_missing} tanesinde tutar girilmedi)` : ""}</dd></div>
            </dl>
            <p className="muted small">Güncelleme: {formatIstanbul(overview.updated_at)} · Europe/Istanbul. Sayılar personelin CRM kayıtlarından gelir; otomatik başarı/başarısızlık değerlendirmesi yapılmaz.</p>
          </div>
          <div className="card table-scroll">
            <h3 style={{ marginTop: 0 }}>Personel bazında (aktivite → sonuç)</h3>
            <table id="staff-performance">
              <thead><tr><th>Personel</th><th>Analiz</th><th>Atanan aktif kayıt</th><th>İletişim</th><th>Ulaşılamadı</th><th>İlgilenen</th><th>Teklif gönderilen</th><th>Kazanılan</th><th>Kaybedilen</th><th>Satış tutarı</th><th>Takip edilen firma</th><th>Geciken takip</th><th>Ort. takip gecikmesi</th><th>Dönüşüm</th></tr></thead>
              <tbody>
                {overview.by_staff.map((r) => (
                  <tr key={r.user_id} data-staff-row={r.name}>
                    <td><strong>{r.name}</strong>{!r.is_active && <span className="muted small"> (pasif)</span>}</td><td>{r.analyses}</td><td>{r.assigned_leads}</td><td>{r.contacts}</td><td>{r.unreachable}</td><td>{r.interested}</td>
                    <td>{r.offers_sent}</td><td>{r.won}</td><td>{r.lost}</td><td>{formatTL(r.sales_total)}</td><td>{r.followed_customers}</td><td>{r.overdue_follow_ups}</td>
                    <td>{r.avg_follow_delay_hours !== null ? `${r.avg_follow_delay_hours} sa` : "—"}</td><td>{r.conversion_offer_to_won !== null ? `%${r.conversion_offer_to_won}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {([["Hizmete göre", overview.by_service], ["Sektöre göre", overview.by_sector]] as [string, RevenueRow[]][]).map(([title, rows]) => (
            <div className="card table-scroll" key={title}>
              <h3 style={{ marginTop: 0 }}>{title}</h3>
              {rows.filter((r) => r.offers || r.sales).length === 0 ? <p className="muted small">Bu dönemde teklif/satış kaydı yok.</p> : (
                <table className="mini-table">
                  <thead><tr><th>Ad</th><th>Teklif</th><th>Satış</th><th>Tutar</th><th>Ortalama</th><th>Dönüşüm</th></tr></thead>
                  <tbody>{rows.filter((r) => r.offers || r.sales).map((r) => <tr key={r.name}><td>{r.name}</td><td>{r.offers}</td><td>{r.sales}</td><td>{formatTL(r.amount)}</td><td>{formatTL(r.average)}</td><td>{r.conversion !== null ? `%${r.conversion}` : r.sample_note ?? "—"}</td></tr>)}</tbody>
                </table>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
