"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BusinessDetail } from "@/lib/types";

const DIMENSION_LABELS: Record<string, string> = {
  web: "Website",
  seo: "SEO",
  google_visibility: "Google Görünürlüğü",
  social: "Sosyal Medya",
  ads: "Reklam",
  design: "Grafik Tasarım",
  print: "Matbaa / Fiziksel Reklam",
};

function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${status}`}>{status}</span>;
}

export default function BusinessDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const businessId = Number(id);

  const [detail, setDetail] = useState<BusinessDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  async function load() {
    try {
      setDetail(await api.getBusinessDetail(businessId));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [businessId]);

  useEffect(() => {
    if (!detail?.latest_analysis_job) return;
    const job = detail.latest_analysis_job;
    if (job.status === "pending" || job.status === "running") {
      setAnalyzing(true);
      const interval = setInterval(async () => {
        const updated = await api.getAnalysisJob(job.id);
        if (updated.status !== "pending" && updated.status !== "running") {
          clearInterval(interval);
          setAnalyzing(false);
          load();
        }
      }, 1200);
      return () => clearInterval(interval);
    } else {
      setAnalyzing(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.latest_analysis_job?.id, detail?.latest_analysis_job?.status]);

  async function handleAnalyze() {
    setError(null);
    setAnalyzing(true);
    try {
      await api.analyzeBusiness(businessId);
      await load();
    } catch (e) {
      setError((e as Error).message);
      setAnalyzing(false);
    }
  }

  if (error) return <main className="container"><p className="error">{error}</p></main>;
  if (!detail) return <main className="container"><p className="muted">Yükleniyor...</p></main>;

  const { business, metrics, findings, opportunity_scores, service_recommendations, competitors, latest_analysis_job } = detail;
  const serviceNameById = new Map(service_recommendations.map((s) => [s.service_id, s.service_name]));

  return (
    <main className="container">
      <p><Link href="/">&larr; İşletme listesine dön</Link></p>

      <h1>
        {business.name}
        {business.is_demo_data && <span className="demo-badge">DEMO DATA — Gerçek Google verisi değildir</span>}
      </h1>
      <p className="muted">
        {business.address} · {business.phone ?? "telefon yok"} · {business.website ?? "web sitesi yok"}
        {business.opening_hours && <> · {business.opening_hours}</>}
        {" · "}
        <a
          href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${business.name} ${business.address ?? ""}`)}`}
          target="_blank"
          rel="noreferrer"
        >
          Google&apos;da Aç
        </a>
      </p>
      {!business.is_demo_data && (
        <p className="muted">Veri kaynağı: OpenStreetMap — © OpenStreetMap contributors (ODbL)</p>
      )}
      <p>
        Rating: {business.google_rating ?? "-"} ({business.google_review_count ?? 0} yorum) · CRM: {business.crm_stage} · Durum: {business.status}
      </p>
      {business.opportunity_score_total !== null && (
        <p>Genel fırsat skoru: <strong>{business.opportunity_score_total}</strong> — Satış önceliği: <strong>{business.sales_priority}</strong></p>
      )}

      <button className="primary" onClick={handleAnalyze} disabled={analyzing}>
        {analyzing ? "Analiz ediliyor..." : "Analiz Et"}
      </button>
      {latest_analysis_job && (
        <p className="muted">
          Son analiz durumu: {latest_analysis_job.status} — aşamalar: {JSON.stringify(latest_analysis_job.stages_status)}
        </p>
      )}

      <h2>Ölçülebilir Veriler (Business Metrics)</h2>
      <table>
        <thead><tr><th>Metrik</th><th>Değer</th><th>Durum</th><th>Kaynak</th><th>Tarih</th></tr></thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m.id}>
              <td>{m.metric_key}</td>
              <td>{m.value ? JSON.stringify(m.value.value) : "-"}</td>
              <td><StatusBadge status={m.status} /></td>
              <td>{m.source}</td>
              <td>{new Date(m.collected_at).toLocaleString("tr-TR")}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Bulgular (Findings) — Kanıta Dayalı</h2>
      {findings.length === 0 && <p className="muted">Henüz bulgu yok. Analiz başlatın.</p>}
      {findings.map((f) => (
        <div className="card" key={f.id}>
          <p>
            <StatusBadge status={f.severity} /> <strong>{f.finding}</strong>{" "}
            <span className="muted">(güven: {f.confidence}, kaynak: {f.source})</span>
          </p>
          <p><em>Kanıt:</em> {f.evidence}</p>
          {f.business_impact && <p><em>İşletmeye etkisi:</em> {f.business_impact}</p>}
          {f.mchttasarim_opportunity && <p><em>Mchttasarım fırsatı:</em> {f.mchttasarim_opportunity}</p>}
          {f.recommended_service_ids.length > 0 && (
            <p><em>Önerilen hizmet(ler):</em> {f.recommended_service_ids.map((id) => serviceNameById.get(id) ?? id).join(", ")}</p>
          )}
        </div>
      ))}

      <h2>Fırsat Skorları (Boyut Bazlı)</h2>
      <table>
        <thead><tr><th>Boyut</th><th>Skor</th><th>Açıklama</th></tr></thead>
        <tbody>
          {opportunity_scores.map((s) => (
            <tr key={s.dimension}>
              <td>{DIMENSION_LABELS[s.dimension] ?? s.dimension}</td>
              <td>{s.status === "insufficient_data" ? "insufficient data" : `${s.score}/100`}</td>
              <td style={{ whiteSpace: "pre-line" }}>{s.reasoning}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Önerilen Mchttasarım Hizmetleri (Rule Engine)</h2>
      <table>
        <thead><tr><th>#</th><th>Hizmet</th><th>Hangi bulgulara dayanıyor</th><th>AI yorumu</th></tr></thead>
        <tbody>
          {service_recommendations.map((s) => (
            <tr key={s.service_id}>
              <td>{s.priority_rank}</td>
              <td>{s.service_name}</td>
              <td>{s.matched_rule}</td>
              <td className="muted">{s.ai_justification ?? "(AI yorumlama atlandı — ANTHROPIC_API_KEY yok)"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Rakip Karşılaştırması</h2>
      {competitors.length === 0 && <p className="muted">Aynı bölge/sektörde karşılaştırılacak başka işletme bulunamadı.</p>}
      {competitors.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Metrik</th>
              <th>Bu İşletme</th>
              {competitors[0].competitors.map((c) => <th key={c.competitor_id}>{c.competitor_name}</th>)}
            </tr>
          </thead>
          <tbody>
            {competitors.map((row) => (
              <tr key={row.metric_key}>
                <td>{row.metric_key}</td>
                <td>
                  {row.business_status === "not_available" ? <StatusBadge status="not_available" /> : JSON.stringify(row.business_value?.value)}
                </td>
                {row.competitors.map((c) => (
                  <td key={c.competitor_id}>
                    {c.status === "not_available" ? <StatusBadge status="not_available" /> : JSON.stringify(c.value?.value)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
