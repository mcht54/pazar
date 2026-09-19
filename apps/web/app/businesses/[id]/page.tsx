"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cameFromList, patchStoredBusiness } from "../../_components/search-store";
import type { BusinessDetail } from "@/lib/types";
import { SalesPlanPanel } from "../../_components/sales-ops";
import {
  CrmPanel,
  GuideModal,
  GuideScopeProvider,
  OpportunitySection,
  AnalysisBadge,
  AddToCrmModal,
  CrmBadge,
  QuickActions,
  SalesNoteModal,
  ScoreBlock,
  GuideButton,
} from "../../_components/sales";
import { AnalysisHistory, AnalysisStateBadge, PriorityBlock, ServiceMatrixSection, WhyProspect } from "../../_components/matrix";
import { useAuth } from "../../_components/auth";
import { AnalysisSections, LevelBadge, SeverityBadge, SocialBlock, SourceStatusPanel, Unverified, Val, VerificationBlock } from "../../_components/analysis";
import {
  ANALYSIS_STATUS_LABELS,
  BUSINESS_STATUS_LABELS,
  COMPETITOR_METRIC_LABELS,
  CONFIDENCE_LABELS,
  METRIC_STATUS_LABELS,
  SOURCE_LABELS,
  STAGE_LABELS,
  STAGE_STATUS_LABELS,
  UNVERIFIED,
  CATEGORY_LABELS,
  crmPatch,
  formatDateTime,
  formatValue,
  metricLabel,
} from "../../_components/labels";

/** Listeden gelindiyse tarayıcı geçmişinde bir adım GERİ gider (liste state'iyle birlikte aynen döner); doğrudan açıldıysa listeye yönlendirir. */
function BackToList() {
  const router = useRouter();
  return (
    <Link
      href="/"
      onClick={(e) => {
        if (cameFromList()) {
          e.preventDefault();
          router.back();
        }
      }}
    >
      ← İşletme listesine dön
    </Link>
  );
}

export default function BusinessDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useAuth();
  const businessId = Number(id);

  const [detail, setDetail] = useState<BusinessDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [showNote, setShowNote] = useState(false);
  const [showGuidePicker, setShowGuidePicker] = useState(false);
  const [noteToAppend, setNoteToAppend] = useState<string | undefined>(undefined);
  const [crmMessage, setCrmMessage] = useState<string | null>(null);
  const [showAddCrm, setShowAddCrm] = useState(false);

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
    const job = detail?.latest_analysis_job;
    if (!job) return;
    if (job.status !== "pending" && job.status !== "running") {
      setAnalyzing(false);
      return;
    }
    setAnalyzing(true);
    const interval = setInterval(async () => {
      const updated = await api.getAnalysisJob(job.id);
      if (updated.status !== "pending" && updated.status !== "running") {
        clearInterval(interval);
        setAnalyzing(false);
        load();
      }
    }, 1500);
    return () => clearInterval(interval);
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

  function scrollToCrm() {
    document.getElementById("crm-panel")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  /** CRM güncellemesinden dönen durumu detaya yansıtır (firma bilgileri + işlem geçmişi). */
  function applyCrmState(state: Parameters<typeof crmPatch>[0] & { history: BusinessDetail["crm_history"] }) {
    setDetail((d) => d && ({ ...d, business: { ...d.business, ...crmPatch(state) }, crm_history: state.history }));
    void load(); // takip listesi (bekleyen + kapananlar) sunucudan tazelenir
  }

  /** ➕ CRM'e Ekle: CRM'de değilse durum + not penceresini açar; zaten CRM'deyse CRM bilgilerine götürür. */
  function handleAddToCrm() {
    if (!detail) return;
    setCrmMessage(null);
    if (!detail.business.in_crm) {
      setShowAddCrm(true);
      return;
    }
    setCrmMessage(`Bu firma zaten CRM'de: durum “${detail.business.crm_stage}”.`);
    scrollToCrm();
  }

  if (error && !detail) return <main className="container"><p className="error">{error}</p><p><BackToList /></p></main>;
  if (!detail) return <main className="container"><p className="muted">Yükleniyor…</p></main>;

  const { business: b, assessment: a, findings, service_recommendations, competitors, latest_analysis_job, metrics } = detail;

  return (
    <GuideScopeProvider value={{ businessId, sectorId: b.sector_id }}>
    <main className="container">
      <p><BackToList /></p>

      <header className="page-header">
        <h1>
          {b.name}
          {b.is_demo_data && <span className="demo-badge">DEMO VERİ — gerçek işletme değil</span>}
        </h1>
        <p className="muted">{b.sector_name} · {b.region_label} · Durum: {BUSINESS_STATUS_LABELS[b.status] ?? b.status} </p>
        <p style={{ margin: "4px 0 0" }}>
          <AnalysisStateBadge business={b} /> <AnalysisBadge business={b} />
          {b.in_crm && <span style={{ marginLeft: 8 }}><CrmBadge business={b} /></span>}
          {b.sales_score !== null && <span className="score-pill" style={{ marginLeft: 8 }}>Satış puanı: {b.sales_score}/100</span>}
        </p>
      </header>

      <QuickActions
        business={b}
        website={b.verification?.website}
        onSalesNote={() => setShowNote(true)}
        onGuides={() => setShowGuidePicker(true)}
        onAddToCrm={handleAddToCrm}
        canSalesNote={can("sales_note")}
      />
      {b.analysis_state === "running" && (
        <p className="notice notice-warn" role="status" id="analysis-running-note">
          ⏳ Yeni analiz sürüyor.{a ? ` Aşağıda gösterilen sonuç ${formatDateTime(a.analyzed_at)} tarihli ÖNCEKİ analizdir; yeni sonuç tamamlanınca güncellenecek.` : ""}
        </p>
      )}
      {b.analysis_state === "failed" && <p className="notice notice-warn" role="status">❌ Son analiz başarısız oldu.{a ? ` Aşağıdaki sonuç ${formatDateTime(a.analyzed_at)} tarihli önceki analizdir.` : ""} “Analizi Yenile” ile yeniden deneyebilirsiniz.</p>}
      {crmMessage && <p className="notice notice-ok" role="status">{crmMessage}</p>}
      {showAddCrm && <AddToCrmModal business={b} onClose={() => setShowAddCrm(false)} onAdded={(state) => { applyCrmState(state); setCrmMessage("✓ Firma CRM'e eklendi."); }} />}

      <CrmPanel business={b} history={detail.crm_history} noteToAppend={noteToAppend} onUpdated={applyCrmState} followUps={detail.follow_ups} onReload={load} />
      <SalesPlanPanel business={b} />
      <AnalysisHistory items={detail.analysis_history ?? []} />
      {showNote && can("sales_note") && <SalesNoteModal businessId={businessId} onClose={() => setShowNote(false)} onAppendToNote={(t) => { setNoteToAppend(t); setTimeout(scrollToCrm, 50); }} />}
      {showGuidePicker && a && <GuidePicker assessment={a} businessId={businessId} sectorId={b.sector_id} onClose={() => setShowGuidePicker(false)} />}

      {error && <p className="error" role="alert">{error}</p>}

      <div className="card">
        <h2>Veri Doğrulama</h2>
        <p className="muted small">
          🟢 DOĞRULANDI: kaynaklardan doğrulandı · 🟠 ÇELİŞKİLİ: kaynaklar farklı bilgi veriyor (manuel kontrol) · 🔴 BULUNAMADI: erişilebilen kaynaklarda yok ·
          ⚪ TEK KAYNAK: yalnızca doğrulanmamış tek kaynakta var. Hiçbir değer tahmin edilmez.
        </p>
        <h3>Kaynak durumları</h3>
        <SourceStatusPanel statuses={b.source_statuses ?? []} />
        <h3 style={{ marginTop: 14 }}>Bilgiler ve kaynakları</h3>
        {Object.keys(b.verification ?? {}).length > 0 ? <VerificationBlock verification={b.verification} /> : (
          <table className="kv">
            <tbody>
              <tr><th>Adres</th><td><Val>{b.address}</Val></td></tr>
              <tr><th>Telefon</th><td><Val>{b.phone}</Val></td></tr>
              <tr><th>Web sitesi</th><td>{b.website ?? <Unverified />}</td></tr>
              <tr><th>Google puanı</th><td><Val>{b.google_rating}</Val></td></tr>
              <tr><th>Google yorum sayısı</th><td><Val>{b.google_review_count}</Val></td></tr>
            </tbody>
          </table>
        )}
        {b.social_accounts.length > 0 && (<><h3 style={{ marginTop: 14 }}>Sosyal medya</h3><SocialBlock accounts={b.social_accounts} /></>)}
        <table className="kv" style={{ marginTop: 12 }}>
          <tbody>
            <tr><th>Konum</th><td>{b.lat && b.lng ? <>{b.lat.toFixed(5)}, {b.lng.toFixed(5)} · <a href={b.maps_url ?? b.maps_search_url} target="_blank" rel="noreferrer">{b.maps_url ? "Google Haritalar'da aç" : "Google Haritalar'da ara"}</a></> : <Unverified />}</td></tr>
            <tr>
              <th>Ham keşif kaynağı</th>
              <td>
                {b.source_label} · Son kontrol: {formatDateTime(b.source_checked_at)}
                {b.source_url && <> · <a href={b.source_url} target="_blank" rel="noreferrer">Kaynak kaydını aç</a></>}
                {b.discovery_source === "osm_overpass" && <div className="muted small">© OpenStreetMap katkıcıları (ODbL lisansı)</div>}
              </td>
            </tr>
          </tbody>
        </table>

        <div className="actions">
          <button className="primary" onClick={handleAnalyze} disabled={analyzing}>
            {analyzing ? "Analiz ediliyor…" : a && b.analyzed_by_me ? "Analizi Yenile" : "Analiz Et"}
          </button>
          {latest_analysis_job && (
            <span className="muted small">
              Son analiz: {ANALYSIS_STATUS_LABELS[latest_analysis_job.status] ?? latest_analysis_job.status} ·{" "}
              {Object.entries(latest_analysis_job.stages_status).map(([k, v]) => `${STAGE_LABELS[k] ?? k}: ${STAGE_STATUS_LABELS[v] ?? v}`).join(" · ")}
            </span>
          )}
        </div>
      </div>

      {!a && <p className="muted">Henüz analiz yok. “Analiz Et” ile Google profili ve web sitesi analizini başlatın.</p>}

      {a && (
        <>
          <div className="card highlight">
            <div className="business-head">
              <h2 style={{ margin: 0 }}>Satış Fırsatı</h2>
              <div className="level-block"><LevelBadge level={a.level} />{a.needs_verification && <div className="verify-note small">Doğrulama gerekli</div>}</div>
            </div>
            <div className="sections">
              <section><div className="label-cap">Neden?</div><p>{a.level_reason}</p></section>
              <section>
                <div className="label-cap">Önerilen Hizmetler</div>
                {a.primary_service ? (
                  <ol className="services">
                    <li><strong>{a.primary_service}</strong> <span className="muted small">(önerilen ilk hizmet)</span></li>
                    {a.secondary_service && <li>{a.secondary_service} <span className="muted small">(ikinci hizmet)</span></li>}
                  </ol>
                ) : <p className="muted">Kanıta dayalı bir hizmet önerisi yok.</p>}
              </section>
              {a.top_opportunity && <section><div className="label-cap">En Önemli Satış Fırsatı</div><p>{a.top_opportunity}</p></section>}
              <section><div className="label-cap">Neden Bu Firmayı Aramalıyım?</div><p>{a.why_call}</p></section>
              <section><div className="label-cap">Satış Görüşmesinde Nereden Başlanmalı?</div><p>{a.talking_point}</p></section>
              <section className="note"><div className="label-cap">Satışta Kullanılabilecek Kısa Not</div><p>{a.sales_note}</p></section>
              {a.verification_steps.length > 0 && (
                <section>
                  <div className="label-cap">Görüşmeden Önce Doğrulanması Gerekenler</div>
                  <ul>{a.verification_steps.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </section>
              )}
            </div>
          </div>

          <WhyProspect items={a.why_prospect ?? []} />
          {a.priority && <PriorityBlock priority={a.priority} />}
          <ScoreBlock score={a.score} />

          {a.service_matrix && a.service_matrix.items?.length > 0
            ? <ServiceMatrixSection matrix={a.service_matrix} />
            : <OpportunitySection evidence={a.opportunities.evidence} possible={a.opportunities.possible} />}

          <h2>Tespit Edilen Eksikler ve Satılabilecek Hizmetler</h2>
          {a.gaps.length === 0 && <p className="muted">Somut bir eksik tespit edilmedi.</p>}
          {a.gaps.map((g) => (
            <div className="card compact" key={`${g.area}-${g.key}`}>
              <p><SeverityBadge severity={g.severity} /> <strong>{g.value}</strong> <span className="muted small">(güven: {CONFIDENCE_LABELS[g.confidence]})</span></p>
              {g.detail && <p className="small"><em>Kanıt:</em> {g.detail}</p>}
              {g.why && <p className="small"><em>Bu eksik neden önemli:</em> {g.why}</p>}
              {g.services.length > 0 && <p className="small"><em>Mchttasarım burada ne satabilir:</em> <strong>{g.services.join(", ")}</strong></p>}
              <GuideButton guideId={g.guide_id} />
            </div>
          ))}

          {a.services.length > 0 && (
            <>
              <h3>Kanıta Dayalı Hizmet Önerileri</h3>
              <table>
                <thead><tr><th>#</th><th>Hizmet</th><th>Hangi bulgulara dayanıyor</th></tr></thead>
                <tbody>
                  {a.services.map((s, i) => (
                    <tr key={s.service}><td>{i + 1}</td><td><strong>{s.service}</strong></td><td>{s.reasons.join("; ")}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {a.possible_services.length > 0 && (
            <>
              <h3>Olası İhtiyaçlar (doğrulama gerektirir)</h3>
              <p className="muted small">Bunlar tespit değil, sektör mantığına dayalı olasılıklardır; satış seviyesini etkilemez. Görüşmede sorulup doğrulanmalıdır.</p>
              <ul>{a.possible_services.map((p) => <li key={p.service}><strong>{p.service}:</strong> {p.basis}</li>)}</ul>
            </>
          )}

          {a.strengths.length > 0 && (
            <>
              <h3>Güçlü Yönler (ölçülen ve sorunsuz alanlar)</h3>
              <p className="muted small">{a.strengths.map((s) => s.label).join(" · ")}</p>
            </>
          )}

          <AnalysisSections business={b} assessment={a} />

          <h2>Rakip Karşılaştırması</h2>
          {competitors.length === 0 && <p className="muted">Aynı bölge ve sektörde karşılaştırılacak başka işletme bulunamadı.</p>}
          {competitors.length > 0 && (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Ölçüm</th>
                    <th>Bu işletme</th>
                    {competitors[0].competitors.map((c) => <th key={c.competitor_id}>{c.competitor_name}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {competitors.map((row) => (
                    <tr key={row.metric_key}>
                      <td>{COMPETITOR_METRIC_LABELS[row.metric_key] ?? row.metric_key}</td>
                      <td>{row.business_status === "not_available" || !row.business_value ? <Unverified /> : formatValue(row.business_value.value)}</td>
                      {row.competitors.map((c) => (
                        <td key={c.competitor_id}>{c.status === "not_available" || !c.value ? <Unverified /> : formatValue(c.value.value)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <details className="card compact">
            <summary>Bulgu kayıtları (kanıt zinciri) — {findings.length}</summary>
            {findings.map((f) => (
              <div key={f.id} className="small" style={{ marginTop: 12 }}>
                <p>
                  <SeverityBadge severity={f.severity} /> <strong>{f.finding}</strong>{" "}
                  <span className="muted">(kategori: {(CATEGORY_LABELS[f.category] ?? f.category)}, kaynak: {SOURCE_LABELS[f.source] ?? f.source}, güven: {CONFIDENCE_LABELS[f.confidence]})</span>
                </p>
                <p><em>Kanıt:</em> {f.evidence}</p>
                {f.mchttasarim_opportunity && <p><em>Fırsat:</em> {f.mchttasarim_opportunity}</p>}
                <p className="muted">Dayandığı ölçüm kayıtları: {f.based_on_metric_ids.join(", ")}</p>
              </div>
            ))}
            {service_recommendations.length > 0 && (
              <p className="muted small" style={{ marginTop: 12 }}>
                Hizmet eşleştirme sırası: {service_recommendations.map((s) => `${s.priority_rank}. ${s.service_name}`).join(" → ")}
              </p>
            )}
          </details>

          <details className="card compact">
            <summary>Ölçüm kayıtları — {metrics.length}</summary>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Ölçüm</th><th>Değer</th><th>Durum</th><th>Kaynak</th><th>Zaman</th></tr></thead>
                <tbody>
                  {metrics.filter((m) => m.metric_key !== "website.signals").map((m) => (
                    <tr key={m.id}>
                      <td>{metricLabel(m.metric_key, m.value?.label)}</td>
                      <td>{m.status === "not_available" ? <Unverified /> : formatValue(m.value?.value)}</td>
                      <td>{METRIC_STATUS_LABELS[m.status] ?? m.status}</td>
                      <td>{SOURCE_LABELS[m.source] ?? m.source}</td>
                      <td>{formatDateTime(m.collected_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
      <p className="muted small">{UNVERIFIED} = kaynak bu bilgiyi vermedi veya erişilemedi; değer tahmin edilmez.</p>
    </main>
    </GuideScopeProvider>
  );
}

/** "💡 Nasıl Çözülür?" — işletmede tespit edilen sorunlardan hangisi için rehber açılacağını seçtirir. */
function GuidePicker({ assessment, businessId, sectorId, onClose }: { assessment: NonNullable<BusinessDetail["assessment"]>; businessId: number; sectorId: number; onClose: () => void }) {
  const [chosen, setChosen] = useState<string | null>(null);
  const items = assessment.gaps.filter((g) => g.guide_id);
  const seen = new Set<string>();
  const unique = items.filter((g) => (seen.has(g.guide_id as string) ? false : (seen.add(g.guide_id as string), true)));
  if (chosen) return <GuideModal guideId={chosen} businessId={businessId} sectorId={sectorId} onClose={onClose} />;
  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-label="Sorun seçin" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head"><h2>💡 Hangi sorun için rehber?</h2><button className="secondary" onClick={onClose}>Kapat ✕</button></div>
        <div className="modal-body">
          {unique.length === 0 ? (
            <p className="muted">Bu işletmede rehbere bağlanabilecek somut bir sorun tespit edilmedi. Genel rehberler için <Link href="/rehber">📚 Çözüm Rehberi</Link> sayfasına bakın.</p>
          ) : (
            <div className="guide-list">
              {unique.map((g) => (
                <button key={g.guide_id} className="guide-item" onClick={() => setChosen(g.guide_id as string)}>
                  <strong>{g.value}</strong>
                  <span className="muted small">{g.services.join(", ")}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
