"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type HealthStatus } from "@/lib/api";
import type { Business, BusinessDetail, CrmState, DiscoveryJob, Region, ReportPeriod, SalesLevel, Sector } from "@/lib/types";
import { AnalysisSections, LevelBadge, QuickList, SocialBlock, SourceStatusPanel, Unverified, Val, VerifiedValue, VerifyBadge } from "./_components/analysis";
import { BUSINESS_STATUS_LABELS, CRM_STAGES, crmPatch, JOB_STATUS_LABELS, SORT_OPTIONS, formatDateTime, telUrl, trSort, whatsappUrl } from "./_components/labels";
import { consumeDashboardStale, enterList, markLeavingList, restoreScroll, takeReloadScroll, usePersistentState, useSessionReady } from "./_components/search-store";
import { AnalysisBadge, CrmCardControl, GuideModal, SalesNoteModal } from "./_components/sales";
import { AnalysisStateBadge, WhyProspect } from "./_components/matrix";
import { useAuth } from "./_components/auth";
import { AnalysisReportCard, CrmSummaryCard, PERIOD_TITLES } from "./_components/report-cards";
import { CallTodayPanel, FollowUpsPanel, FunnelCard, RevenueCard } from "./_components/sales-ops";

const MAX_POLL_MS = 15 * 60 * 1000;
const LEVELS: SalesLevel[] = ["Yüksek", "Orta", "Düşük", "Belirsiz"];

export default function HomePage() {
  const { can } = useAuth();
  // Arama ekranının state'i sayfalar arası korunur (liste → detay → geri): bkz. _components/search-store.ts
  const [regions, setRegions] = usePersistentState<Region[]>("search.regions", []);
  const [sectors, setSectors] = usePersistentState<Sector[]>("search.sectors", []);
  const [provinceId, setProvinceId] = usePersistentState<number | null>("search.provinceId", null);
  const [districtId, setDistrictId] = usePersistentState<number | null>("search.districtId", null);
  const [sectorId, setSectorId] = usePersistentState<number | null>("search.sectorId", null);
  const [sectorFilter, setSectorFilter] = usePersistentState("search.sectorFilter", "");
  const [targetCount, setTargetCount] = usePersistentState("search.targetCount", 30);

  const [job, setJob] = usePersistentState<DiscoveryJob | null>("search.job", null);
  const [businesses, setBusinesses] = usePersistentState<Business[]>("search.businesses", []);
  const [loadedKey, setLoadedKey] = usePersistentState<string | null>("search.loadedKey", null); // hangi bölge+sektör için liste yüklendi
  const [levelFilter, setLevelFilter] = usePersistentState<SalesLevel | "Hepsi" | "Bekleyen">("search.levelFilter", "Hepsi");
  const [sortKey, setSortKey] = usePersistentState<string>("search.sort", "priority");
  const [hideAnalyzed, setHideAnalyzed] = usePersistentState("search.hideAnalyzed", false);
  const [crmFilter, setCrmFilter] = usePersistentState<string>("search.crmFilter", "Hepsi");
  const [phoneOnly, setPhoneOnly] = usePersistentState("search.phoneOnly", false);
  const [todayVersion, setTodayVersion] = useState(0);
  const [reportVersion, setReportVersion] = useState(0); // analiz raporu / CRM özeti yeniden çekilsin
  const [period, setPeriod] = usePersistentState<ReportPeriod | null>("report.period", null); // "Bugün 42" tıklanınca o dönemin firmaları
  const [periodList, setPeriodList] = useState<{ items: Business[]; analyses: number; count: number } | null>(null);
  const [periodError, setPeriodError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = usePersistentState<HealthStatus | null>("search.health", null);
  const ready = useSessionReady(); // tüm usePersistentState çağrılarından sonra: geri yükleme (yenileme) tamamlandı mı?
  const pollStartedAt = useRef(Date.now());

  // Detaydan geri dönüldüyse liste scroll konumu yüklenir; ayrıca scroll konumu sürekli izlenir.
  useLayoutEffect(() => {
    const { restoreTo, stopTracking } = enterList();
    if (restoreTo !== null) restoreScroll(restoreTo);
    return stopTracking;
  }, []);

  // Sabit veriler yalnızca depoda yoksa çekilir (geri dönüşte yeniden sorgu yok).
  useEffect(() => {
    if (regions.length === 0) api.getRegions().then(setRegions).catch((e) => setError(e.message));
    if (sectors.length === 0) api.getSectors().then(setSectors).catch((e) => setError(e.message));
    if (!health) api.getHealth().then(setHealth).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const provinces = useMemo(() => regions.filter((r) => r.level === "il").sort((a, b) => trSort(a.name, b.name)), [regions]);
  const districts = useMemo(
    () => regions.filter((r) => r.level === "ilce" && r.parent_region_id === provinceId).sort((a, b) => trSort(a.name, b.name)),
    [regions, provinceId]
  );
  const province = provinces.find((p) => p.id === provinceId) ?? null;
  const effectiveRegionId = districtId ?? provinceId;

  const groupedSectors = useMemo(() => {
    const needle = sectorFilter.trim().toLocaleLowerCase("tr");
    const groups = new Map<string, Sector[]>();
    for (const s of sectors) {
      if (needle && !s.name.toLocaleLowerCase("tr").includes(needle) && sectorId !== s.id) continue;
      const key = s.group_name ?? "Diğer";
      groups.set(key, [...(groups.get(key) ?? []), s]);
    }
    return [...groups.entries()]
      .sort(([a], [b]) => trSort(a, b))
      .map(([name, list]) => [name, list.sort((a, b) => trSort(a.name, b.name))] as const);
  }, [sectors, sectorFilter, sectorId]);

  // Seçilen bölge + sektör için daha önce bulunmuş işletmeleri (varsa) göster.
  // Yalnızca geri yükleme bittikten sonra çalışır (ilk render'ın boş seçimleriyle yanlış sorgu/temizleme yapılmasın).
  const listKey = `${effectiveRegionId}:${sectorId}`;
  useEffect(() => {
    if (!ready || job || !effectiveRegionId || !sectorId || loadedKey === listKey) return;
    let cancelled = false; // seçim hızlı değişirse eski isteğin cevabı yenisini ezmesin
    api.getBusinesses({ region_id: effectiveRegionId, sector_id: sectorId }).then((results) => {
      if (cancelled) return;
      setBusinesses(results);
      setLoadedKey(listKey);
      setLevelFilter("Hepsi");
      setCrmFilter("Hepsi");
    }).catch(() => {});
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, effectiveRegionId, sectorId, job, loadedKey]);

  // Seçim eksik kaldıysa (ör. sektör temizlendi) eski aramanın sonuçları ekranda kalmasın.
  useEffect(() => {
    if (!ready || job || (effectiveRegionId && sectorId)) return;
    if (businesses.length > 0) setBusinesses([]);
    if (loadedKey !== null) setLoadedKey(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, effectiveRegionId, sectorId, job]);

  // Yenileme sonrası: iş kaydı geri geldi ama sonuç listesi saklanamadıysa (depolama kotası) sonuçları API'den yeniden al.
  const recovered = useRef(false);
  useEffect(() => {
    if (!ready || recovered.current) return;
    recovered.current = true;
    if (job && businesses.length === 0) api.getBusinesses({ job_id: job.id }).then(setBusinesses).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  const jobActive = !!job && (job.status === "pending" || job.status === "running");
  const analysisPending = businesses.some((b) => b.status === "discovered" || b.status === "analyzing");
  const busy = jobActive || (!!job && analysisPending);

  useEffect(() => {
    if (!job || !busy) return;
    const interval = setInterval(async () => {
      try {
        const [updatedJob, results] = await Promise.all([api.getDiscoveryJob(job.id), api.getBusinesses({ job_id: job.id })]);
        setJob(updatedJob);
        setBusinesses(results);
      } catch (e) {
        setError((e as Error).message);
      }
      if (Date.now() - pollStartedAt.current > MAX_POLL_MS) clearInterval(interval);
    }, 2000);
    return () => clearInterval(interval);
  }, [job?.id, busy]);

  async function handleDiscover() {
    setError(null);
    if (!effectiveRegionId || !sectorId) {
      setError("Lütfen şehir ve sektör seçin (ilçe isteğe bağlıdır).");
      return;
    }
    try {
      const created = await api.createDiscoveryJob(effectiveRegionId, sectorId, targetCount);
      pollStartedAt.current = Date.now();
      setLoadedKey(null);
      setBusinesses([]);
      setLevelFilter("Hepsi");
      setCrmFilter("Hepsi");
      setPeriod(null); // yeni arama: analiz raporu dönem filtresi kapanır, yeni sonuçlar görünür
      setJob(created);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = { Yüksek: 0, Orta: 0, Düşük: 0, Belirsiz: 0, Bekleyen: 0 };
    for (const b of businesses) c[b.sales_level ?? "Bekleyen"] += 1;
    return c;
  }, [businesses]);

  const visible = useMemo(() => {
    const filtered = businesses.filter((b) =>
      (levelFilter === "Hepsi" ? true : levelFilter === "Bekleyen" ? !b.sales_level : b.sales_level === levelFilter) &&
      (!hideAnalyzed || !b.previously_analyzed) &&
      (crmFilter === "Hepsi" || (crmFilter === "CRM'de değil" ? !b.in_crm : b.in_crm && b.crm_stage === crmFilter)) &&
      (!phoneOnly || !!b.phone)
    );
    const num = (v: number | null | undefined) => (v === null || v === undefined ? -Infinity : v);
    // "priority": API sırası (seviye → puan → ulaşılabilirlik) aynen korunur.
    if (sortKey === "score") return [...filtered].sort((a, b) => num(b.sales_score) - num(a.sales_score));
    if (sortKey === "rating") return [...filtered].sort((a, b) => num(b.google_rating) - num(a.google_rating));
    if (sortKey === "reviews") return [...filtered].sort((a, b) => num(b.google_review_count) - num(a.google_review_count));
    if (sortKey === "name") return [...filtered].sort((a, b) => trSort(a.name, b.name));
    return filtered;
  }, [businesses, levelFilter, hideAnalyzed, crmFilter, phoneOnly, sortKey]);
  const previouslyCount = businesses.filter((b) => b.previously_analyzed).length;

  // Tam sayfa yenilemeden sonra liste çizilince kaldığı scroll konumuna dön (bir kez).
  useEffect(() => {
    if (!ready || visible.length === 0) return;
    const y = takeReloadScroll();
    if (y !== null) restoreScroll(y);
  }, [ready, visible.length]);

  /** Bir firma bu ekrandan CRM'e alındığında/güncellendiğinde: sonuç listeleri, "bugün" paneli, CRM özeti ve analiz raporu tazelenir. */
  function handleCrmChanged(id: number, state: CrmState) {
    const patch = crmPatch(state);
    setBusinesses((prev) => prev.map((b) => (b.id === id ? { ...b, ...patch } : b)));
    setPeriodList((prev) => (prev ? { ...prev, items: prev.items.map((b) => (b.id === id ? { ...b, ...patch } : b)) } : prev));
    setTodayVersion((v) => v + 1);
    setReportVersion((v) => v + 1);
  }

  // Analiz raporundaki dönem seçilince (Bugün/Bu Hafta/Bu Ay/Toplam) o dönemde analizi tamamlanan firmaları getir.
  useEffect(() => {
    if (!ready || !period) { setPeriodList(null); setPeriodError(null); return; }
    let cancelled = false;
    api.getAnalyzedBusinesses(period)
      .then((r) => { if (!cancelled) { setPeriodList({ items: r.items, analyses: r.analyses, count: r.businesses_count }); setPeriodError(null); } })
      .catch((e) => { if (!cancelled) setPeriodError(e.message); });
    return () => { cancelled = true; };
  }, [ready, period, reportVersion]);

  // Bir analiz tamamlandıkça (arama işi ilerledikçe) rapor sayaçları yenilensin.
  useEffect(() => {
    if (job) setReportVersion((v) => v + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.analyzed_count, job?.status]);

  async function handleExport(format: "csv" | "xlsx") {
    setError(null);
    setExporting(format);
    try {
      await api.exportBusinesses(visible.map((b) => b.id), format);
    } catch (e) {
      setError(`Dışa aktarma başarısız: ${(e as Error).message}`);
    } finally {
      setExporting(null);
    }
  }

  const discoveryPct = job ? Math.min(100, Math.round(((job.found_new + job.found_existing) / Math.max(1, job.target_count)) * 100)) : 0;
  const analysisPct = job && job.total_count > 0 ? Math.round((job.analyzed_count / job.total_count) * 100) : 0;

  return (
    <main className="container container-wide">
      <header className="page-header">
        <h1>Mchttasarım Satış Fırsatı Analizi</h1>
        <p className="lead">
          Şehir → ilçe → sektör seçin. Sistem gerçek işletmeleri bulur, Google profilini ve web sitesini analiz eder,
          Mchttasarım&apos;ın gerçekten satış yapabileceği işletmeleri gerekçeleriyle öne çıkarır.
        </p>
      </header>

      {health && (
        <div className={health.discovery_provider === "mock" ? "notice notice-warn" : "notice notice-ok"}>
          {health.discovery_provider === "google_maps" && <strong>Veri kaynağı: Google Haritalar (herkese açık sayfa, API anahtarı gerekmez)</strong>}
          {health.discovery_provider === "google" && <strong>Veri kaynağı: Google Places API</strong>}
          {health.discovery_provider === "mock" && <strong>DİKKAT: Demo (sahte) veri modu açık — gösterilen işletmeler gerçek değildir (yalnızca test için).</strong>}
          {health.discovery_provider === "google_maps" && (
            <div className="small">
              İşletmeler Google Haritalar&apos;da aranır; her işletme ayrıca Google profilinde, Bing Haritalar&apos;da ve resmi web sitesinde araştırılıp çapraz doğrulanır.
              Bir kaynak (ör. Google Arama) otomatik erişimi engellerse durumu kartta ERİŞİLEMEDİ olarak gösterilir; engel aşılmaz, veri uydurulmaz.
            </div>
          )}
        </div>
      )}

      <div className="home-grid">
      <div className="home-main">
      <CallTodayPanel version={todayVersion + reportVersion} onChanged={() => setReportVersion((v) => v + 1)} />
      <TodayPanel version={todayVersion} onCrmChanged={handleCrmChanged} />

      <div className="card">
        <div className="form-row">
          <div className="form-field">
            <label htmlFor="il">Şehir</label>
            <select
              id="il"
              value={provinceId ?? ""}
              onChange={(e) => {
                setProvinceId(e.target.value ? Number(e.target.value) : null);
                setDistrictId(null);
                setJob(null);
              }}
            >
              <option value="">Şehir seçiniz</option>
              {provinces.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </div>

          <div className="form-field">
            <label htmlFor="ilce">İlçe</label>
            <select
              id="ilce"
              value={districtId ?? ""}
              disabled={!provinceId}
              onChange={(e) => {
                setDistrictId(e.target.value ? Number(e.target.value) : null);
                setJob(null);
              }}
            >
              <option value="">
                {provinceId ? `İl merkezi çevresi (yaklaşık ${Math.round((province?.search_radius_m ?? 0) / 1000)} km yarıçap)` : "Önce şehir seçiniz"}
              </option>
              {districts.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </div>

          <div className="form-field">
            <label htmlFor="sektor">Sektör ({sectors.length})</label>
            <input
              type="search"
              placeholder="Sektör ara… (ör. işitme)"
              value={sectorFilter}
              onChange={(e) => setSectorFilter(e.target.value)}
              aria-label="Sektör ara"
            />
            <select
              id="sektor"
              value={sectorId ?? ""}
              onChange={(e) => {
                setSectorId(e.target.value ? Number(e.target.value) : null);
                setJob(null);
              }}
            >
              <option value="">Sektör seçiniz</option>
              {groupedSectors.map(([group, list]) => (
                <optgroup key={group} label={group}>
                  {list.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
            {sectorFilter && groupedSectors.length === 0 && <span className="muted small">Bu ada uyan sektör yok.</span>}
          </div>

          <div className="form-field narrow">
            <label htmlFor="adet">Taranacak işletme sayısı</label>
            <input id="adet" type="number" min={1} max={100} value={targetCount} onChange={(e) => setTargetCount(Number(e.target.value))} />
          </div>

          <button className="primary" onClick={handleDiscover} disabled={jobActive}>
            {jobActive ? "Taranıyor…" : "Satış Fırsatlarını Bul"}
          </button>
        </div>

        {error && <p className="error" role="alert">{error}</p>}

        {job && (
          <div className="progress-block">
            <p>
              <strong>{JOB_STATUS_LABELS[job.status] ?? job.status}</strong> — {job.total_count} işletme bulundu
              {job.total_count > 0 && <> · {job.analyzed_count} analiz edildi{job.analyzing_count > 0 && `, ${job.analyzing_count} analiz ediliyor`}{job.failed_analysis_count > 0 && `, ${job.failed_analysis_count} analiz başarısız`}</>}
            </p>
            {jobActive && (
              <>
                <div className="progress-bar"><div className="progress-bar-fill" style={{ width: `${discoveryPct}%` }} /></div>
                <p className="muted small">İşletmeler Google Haritalar&apos;da aranıyor. Bu adım bölgeye göre 15–60 saniye sürebilir.</p>
              </>
            )}
            {job.total_count > 0 && (
              <>
                <div className="progress-bar"><div className="progress-bar-fill analysis" style={{ width: `${analysisPct}%` }} /></div>
                <p className="muted small">Analiz ilerlemesi: her işletme Google Haritalar, Bing Haritalar, resmi web sitesi ve diğer kaynaklarda araştırılıp çapraz doğrulanıyor (işletme başına ~30–60 sn); sonuçlar geldikçe liste otomatik güncellenir.</p>
              </>
            )}
            {job.status === "failed" && job.error_message && <p className="error">Hata: {job.error_message}</p>}
            {job.status === "completed" && job.total_count === 0 && (
              <p className="muted">Bu bölge ve sektör için Google Haritalar'da işletme bulunamadı. Başka bir ilçe veya sektör deneyin.</p>
            )}
            {job.item_errors.length > 0 && (
              <ul className="muted small">
                {job.item_errors.map((e, i) => <li key={i}>{e.external_ref}: {e.reason}</li>)}
              </ul>
            )}
          </div>
        )}
      </div>

      {period && (
        <section id="period-view">
          <div className="results-head">
            <h2>{period === "today" ? "📅" : period === "week" ? "📆" : period === "month" ? "🗓️" : "📈"} {PERIOD_TITLES[period]}{periodList ? ` (${periodList.count})` : ""}</h2>
            <button className="secondary" onClick={() => setPeriod(null)}>✕ Filtreyi kaldır (arama sonuçlarına dön)</button>
          </div>
          {periodList && (
            <p className="muted small">
              {periodList.analyses} analiz · {periodList.count} benzersiz firma. {periodList.analyses !== periodList.count && "Aynı firma birden çok kez analiz edildiyse her analiz ayrı sayılır. "}
              En son analiz edilen üstte.
            </p>
          )}
          {periodError && <p className="error">{periodError}</p>}
          {!periodList && !periodError && <p className="muted">Yükleniyor…</p>}
          {periodList && periodList.items.length === 0 && <p className="muted">Bu dönemde tamamlanan analiz yok.</p>}
          {periodList?.items.map((b) => <BusinessCard key={b.id} business={b} onCrmChanged={handleCrmChanged} />)}
        </section>
      )}

      {!period && businesses.length > 0 && (
        <>
          <div className="results-head">
            <h2>Öncelikli Müşteriler ({businesses.length} işletme)</h2>
            <div className="chips" role="tablist" aria-label="Satış fırsatı filtresi">
              <button className={`chip ${levelFilter === "Hepsi" ? "active" : ""}`} onClick={() => setLevelFilter("Hepsi")}>Hepsi ({businesses.length})</button>
              {LEVELS.map((l) => (
                <button key={l} className={`chip ${levelFilter === l ? "active" : ""}`} onClick={() => setLevelFilter(l)}>{l} ({counts[l]})</button>
              ))}
              {counts.Bekleyen > 0 && (
                <button className={`chip ${levelFilter === "Bekleyen" ? "active" : ""}`} onClick={() => setLevelFilter("Bekleyen")}>Analiz bekleyen ({counts.Bekleyen})</button>
              )}
            </div>
          </div>
          <div className="toolbar">
            <label className="small" htmlFor="sort">Sıralama:{" "}
              <select id="sort" value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
                {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            <label className="small" htmlFor="crmf">CRM durumu:{" "}
              <select id="crmf" value={crmFilter} onChange={(e) => setCrmFilter(e.target.value)}>
                <option value="Hepsi">Hepsi</option>
                <option value="CRM'de değil">CRM&apos;de değil</option>
                {CRM_STAGES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={hideAnalyzed} onChange={(e) => setHideAnalyzed(e.target.checked)} />
              Daha önce analiz edilenleri gizle ({previouslyCount})
            </label>
            <label className="check">
              <input type="checkbox" checked={phoneOnly} onChange={(e) => setPhoneOnly(e.target.checked)} />
              Yalnızca telefonu olanlar
            </label>
            <span style={{ flex: 1 }} />
            {can("export") && <button className="secondary" onClick={() => handleExport("xlsx")} disabled={exporting !== null || visible.length === 0}>
              {exporting === "xlsx" ? "Hazırlanıyor…" : `📊 Excel (${visible.length})`}
            </button>}
            {can("export") && <button className="secondary" onClick={() => handleExport("csv")} disabled={exporting !== null || visible.length === 0}>
              {exporting === "csv" ? "Hazırlanıyor…" : `⬇ CSV (${visible.length})`}
            </button>}
          </div>
          <p className="muted small">
            Varsayılan sıralama = satış ÖNCELİĞİ: yalnızca skora değil; skor, satılabilir hizmet sayısı, hizmetlerin ticari anlamlılığı ve analizin tamamlanma durumu birlikte değerlendirilir. Bir firmanın neden üstte olduğunu kartındaki “Neden üstte?” bağlantısından görebilirsiniz.
            {businesses.some((b) => b.is_demo_data) && " DEMO veri içeren kayıtlar gerçek işletme değildir."}
          </p>

          {visible.map((b) => <BusinessCard key={b.id} business={b} onCrmChanged={handleCrmChanged} />)}
          {visible.length === 0 && <p className="muted">Bu filtreye uyan işletme yok.</p>}
        </>
      )}
      </div>

      <aside className="home-side" aria-label="Rapor ve CRM özeti">
        <AnalysisReportCard version={reportVersion} active={period} onSelect={setPeriod} />
        <CrmSummaryCard version={reportVersion} />
        <FollowUpsPanel version={reportVersion} onChanged={() => setReportVersion((v) => v + 1)} />
        {can("sales_reports") && <FunnelCard version={reportVersion} />}
        {can("sales_reports") && <RevenueCard version={reportVersion} />}
      </aside>
      </div>
    </main>
  );
}

function BusinessCard({ business: b, onCrmChanged }: { business: Business; onCrmChanged: (id: number, state: CrmState) => void }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<BusinessDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [showNote, setShowNote] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [showWhyTop, setShowWhyTop] = useState(false);
  const { can } = useAuth();

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !detail) {
      setLoading(true);
      try {
        setDetail(await api.getBusinessDetail(b.id));
      } catch (e) {
        setDetailError((e as Error).message);
      } finally {
        setLoading(false);
      }
    }
  }

  const analyzed = b.sales_level !== null;
  const v = b.verification ?? {};
  const researched = Object.keys(v).length > 0;
  const summaryKeys = ["address", "phone", "website", "rating", "review_count"];

  return (
    <article className={`card business ${analyzed ? "" : "pending"}`}>
      <div className="business-head">
        <div>
          <div className="label-cap">İşletme</div>
          <h3><Link href={`/businesses/${b.id}`} onClick={markLeavingList}>{v.name?.value ?? b.name}</Link></h3>
          <p className="muted small">
            {b.sector_name} · {b.province_name ?? ""}{b.district_name ? ` / ${b.district_name}` : ""}
            {b.is_demo_data && <span className="demo-badge">DEMO VERİ — gerçek işletme değil</span>}
          </p>
          <p style={{ margin: "4px 0 0", display: "flex", gap: 6, flexWrap: "wrap", alignItems: "flex-start" }}>
            <AnalysisStateBadge business={b} />
            <AnalysisBadge business={b} />
            {b.in_crm && <CrmCardControl business={b} onChanged={(state) => onCrmChanged(b.id, state)} />}
          </p>
          {b.primary_service && <p className="small" style={{ margin: "6px 0 0" }} data-testid="card-service"><strong>Önerilen hizmet:</strong> {b.primary_service}</p>}
          {b.prospect_kind && (
            <p style={{ margin: "4px 0 0" }}>
              <span className="prospect-badge" title={b.prospect_reason ?? undefined}>⛔ {b.prospect_label} — müşteri adayı değil</span>
            </p>
          )}
        </div>
        <div className="level-block">
          <div className="label-cap">Satış Fırsatı</div>
          <LevelBadge level={b.sales_level} />
          {b.sales_score !== null && (
            <div style={{ marginTop: 4 }}>
              <span className={`score-pill ${b.sales_score >= 45 ? "score-high" : b.sales_score >= 20 ? "score-mid" : ""}`} title={b.score_band ?? undefined}>Puan: {b.sales_score}/100</span>
            </div>
          )}
          {b.priority_score !== null && (
            <div className="card-priority" data-testid="card-priority">
              <button className="link-btn" onClick={() => setShowWhyTop((x) => !x)} aria-expanded={showWhyTop}>Öncelik {b.priority_score} · Neden üstte?</button>
            </div>
          )}
          {b.needs_verification && <div className="verify-note small">Doğrulama gerekli</div>}
        </div>
      </div>
      {showWhyTop && b.priority_reasons.length > 0 && (
        <ul className="small priority-reasons" data-testid="priority-reasons">{b.priority_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
      )}

      {/* ---- hızlı eylemler: 📞 Ara · 💬 WhatsApp · 🗺️ Google Maps · 🌐 Web Sitesi · 📋 CRM · 💡 Nasıl Çözülür? · 📝 Satış Notu */}
      <div className="card-actions" role="toolbar" aria-label="Firma eylemleri">
        {telUrl(b.phone) && <a className="qa-btn" href={telUrl(b.phone)!}>📞 Ara</a>}
        {whatsappUrl(b.phone) && <a className="qa-btn" href={whatsappUrl(b.phone)!} target="_blank" rel="noreferrer">💬 WhatsApp</a>}
        <a className="qa-btn" href={b.maps_url ?? b.maps_search_url} target="_blank" rel="noreferrer">🗺️ Google Maps</a>
        {v.website?.status === "dogrulandi" && v.website.value
          ? <a className="qa-btn" href={v.website.value} target="_blank" rel="noreferrer">🌐 Web Sitesi</a>
          : <span className="qa-btn qa-disabled" title="Doğrulanmış web sitesi yok">🌐 Web sitesi doğrulanamadı</span>}
        <CrmCardControl business={b} asButton onChanged={(state) => onCrmChanged(b.id, state)} />
        {analyzed && <button className="qa-btn" onClick={() => setShowGuide(true)}>💡 Nasıl Çözülür?</button>}
        {analyzed && can("sales_note") && <button className="qa-btn" onClick={() => setShowNote(true)}>📝 Satış Notu</button>}
      </div>
      {showGuide && (b.top_guide_id
        ? <GuideModal guideId={b.top_guide_id} businessId={b.id} onClose={() => setShowGuide(false)} />
        : <div className="modal-overlay" onClick={() => setShowGuide(false)}><div className="modal" onClick={(e) => e.stopPropagation()}><div className="modal-body"><p>Bu firma için rehbere bağlanan somut bir sorun yok. <Link href="/rehber">📚 Çözüm Rehberi</Link> sayfasından genel rehberlere bakabilirsiniz.</p><button className="secondary" onClick={() => setShowGuide(false)}>Kapat</button></div></div></div>)}
      {showNote && <SalesNoteModal businessId={b.id} onClose={() => setShowNote(false)} />}
      <WhyProspect items={b.why_prospect} compact />

      {/* ---- işletme bilgileri: değer + doğrulama durumu */}
      <div className="facts-verified">
        <div><div className="fv-label">Kategori</div>{researched ? <VerifiedValue field={v.category} /> : <Val>{b.category_label}</Val>}</div>
        <div><div className="fv-label">Adres</div>{researched ? <VerifiedValue field={v.address} /> : <Val>{b.address}</Val>}</div>
        <div><div className="fv-label">Telefon</div>{researched ? <VerifiedValue field={v.phone} /> : <Val>{b.phone}</Val>}</div>
        <div>
          <div className="fv-label">Web sitesi</div>
          {researched ? <VerifiedValue field={v.website} /> : (b.website ? <a href={b.website} target="_blank" rel="noreferrer">{b.website}</a> : <Unverified />)}
        </div>
        <div><div className="fv-label">Google puanı</div>{researched ? <VerifiedValue field={v.rating} /> : <Val>{b.google_rating}</Val>}</div>
        <div><div className="fv-label">Google yorum sayısı</div>{researched ? <VerifiedValue field={v.review_count} /> : <Val>{b.google_review_count}</Val>}</div>
        <div>
          <div className="fv-label">Google Maps</div>
          {b.maps_url ? <a href={b.maps_url} target="_blank" rel="noreferrer">Google Haritalar'da aç</a> : (
            <>{researched ? <VerifiedValue field={v.maps_url} /> : <Unverified />}<div className="small"><a href={b.maps_search_url} target="_blank" rel="noreferrer">Haritalarda ara (elle kontrol)</a></div></>
          )}
        </div>
      </div>

      {!analyzed && (
        <p className="muted">
          {b.status === "analysis_failed" ? "Analiz başarısız oldu. Detay sayfasından yeniden deneyebilirsiniz." : `${BUSINESS_STATUS_LABELS[b.status] ?? b.status}… Google, web sitesi ve diğer kaynaklar araştırılıyor.`}
        </p>
      )}

      {analyzed && (
        <div className="sections">
          <section>
            <div className="label-cap">Veri Doğrulama</div>
            <div className="verify-chips">
              {summaryKeys.filter((k) => v[k]).map((k) => (
                <span key={k} className="verify-chip">{v[k].label}: <VerifyBadge field={v[k]} /></span>
              ))}
            </div>
            <SourceStatusPanel statuses={b.source_statuses ?? []} />
          </section>

          <div className="two-col">
            <section>
              <div className="label-cap">Web Sitesi Analizi</div>
              {b.web_quick.length > 0 ? <QuickList rows={b.web_quick} /> : <p className="small">{b.web_summary}</p>}
            </section>
            <section>
              <div className="label-cap">Google Profil Analizi</div>
              {b.gbp_quick.some((r) => r.state !== "DOĞRULANAMADI") ? <QuickList rows={b.gbp_quick} /> : <p className="small">{b.gbp_summary}</p>}
            </section>
          </div>

          {b.social_accounts.length > 0 && (
            <section>
              <div className="label-cap">Sosyal Medya</div>
              <SocialBlock accounts={b.social_accounts} />
            </section>
          )}

          <section className="note">
            <div className="label-cap">Satış Fırsatı — {b.sales_level}</div>
            <p><strong>Neden?</strong> {b.sales_reason}</p>
            {b.primary_service ? (
              <>
                <p><strong>Önerilen hizmet:</strong> {b.primary_service}</p>
                {b.top_opportunity && <p><strong>Somut neden:</strong> {b.top_opportunity}</p>}
                {b.secondary_service && <p><strong>İkinci fırsat:</strong> {b.secondary_service}</p>}
              </>
            ) : <p className="muted">Bu işletme için kanıta dayalı bir hizmet önerisi yok.</p>}
          </section>

          {b.gap_summary.length > 0 && (
            <section>
              <div className="label-cap">Tespit Edilen Eksikler</div>
              <ul>{b.gap_summary.map((g, i) => <li key={i}>{g}</li>)}</ul>
            </section>
          )}

          <section>
            <div className="label-cap">Neden Bu Firmayı Aramalıyım?</div>
            <p>{b.why_call}</p>
          </section>
          {b.talking_point && (
            <section>
              <div className="label-cap">Satış Görüşmesinde Nereden Başlanmalı?</div>
              <p>{b.talking_point}</p>
            </section>
          )}
          <section className="note">
            <div className="label-cap">Satışta Kullanılabilecek Kısa Not</div>
            <p>{b.sales_note}</p>
          </section>
        </div>
      )}

      <div className="card-footer">
        <span className="muted small">
          Ham keşif kaynağı: {b.source_label}{b.source_url && <> · <a href={b.source_url} target="_blank" rel="noreferrer">kayıt</a></>} · Son kontrol: {formatDateTime(b.source_checked_at)}
        </span>
        <span style={{ display: "inline-flex", gap: 8, flexWrap: "wrap" }}>
          <Link className="qa-btn" href={`/businesses/${b.id}`} onClick={markLeavingList}>Detaya Git →</Link>
          {analyzed && <button className="secondary" onClick={toggle}>{open ? "Ayrıntıları gizle" : "Tüm analiz ayrıntıları"}</button>}
        </span>
      </div>

      {open && (
        <div className="expanded">
          {loading && <p className="muted">Yükleniyor…</p>}
          {detailError && <p className="error">{detailError}</p>}
          {detail?.assessment && <AnalysisSections business={b} assessment={detail.assessment} />}
        </div>
      )}
    </article>
  );
}

/** 🎯 Bugünün potansiyel müşterileri: analizi bitmiş, henüz aranmamış/takipteki, puanı yüksek işletmeler (gerçek analiz verisinden). */
function TodayPanel({ version, onCrmChanged }: { version: number; onCrmChanged: (id: number, state: CrmState) => void }) {
  const [items, setItems] = usePersistentState<Business[] | null>("dash.today", null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stale = consumeDashboardStale();
    if (items !== null && !stale && version === 0) return;
    api.getToday(10).then((r) => { setItems(r); setError(null); }).catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  return (
    <section className="card today" aria-label="Bugünün potansiyel müşterileri">
      <h2>🎯 BUGÜNÜN POTANSİYEL MÜŞTERİLERİ</h2>
      <p className="muted small">
        Analizi tamamlanmış, henüz görüşme aşamasına geçmemiş (Yeni · Aranacak · Takip Bekliyor · Daha Sonra Ara) işletmeler, satış puanına göre. Puan yalnızca gerçek analiz bulgularından hesaplanır.
        Rakip firmalar (web tasarım, reklam ajansı, matbaa vb.), kamu kurumları/devlet okulları ve Mchttasarım&apos;ın kendisi bu listede gösterilmez.
      </p>
      {error && <p className="error">{error}</p>}
      {items === null && !error && <p className="muted">Yükleniyor…</p>}
      {items !== null && items.length === 0 && (
        <p className="muted">Şu an listelenecek uygun işletme yok. Aşağıdan bir şehir ve sektör seçip arama yapın; analiz tamamlandıkça en güçlü fırsatlar burada görünür.</p>
      )}
      {items?.map((b) => {
        const tel = telUrl(b.phone);
        const wa = whatsappUrl(b.phone);
        const tone = (b.sales_score ?? 0) >= 45 ? "score-high" : (b.sales_score ?? 0) >= 20 ? "score-mid" : "score-low";
        return (
          <div className="today-row" key={b.id}>
            <div className={`today-score ${tone}`} title={b.score_band ?? undefined}>{b.sales_score ?? "—"}<div className="muted small" style={{ fontWeight: 400 }}>/100</div></div>
            <div>
              <strong><Link href={`/businesses/${b.id}`} onClick={markLeavingList}>{b.name}</Link></strong>
              <div className="muted small">{b.sector_name} · {b.region_label}</div>
              <div className="small"><strong>Ana sorun:</strong> {b.top_problem ?? <Unverified text="Belirgin sorun tespit edilmedi" />}</div>
              <div className="small"><strong>Önerilen hizmet:</strong> {b.primary_service ?? <Unverified text="Kanıta dayalı öneri yok" />}</div>
              <WhyProspect items={b.why_prospect} compact />
              {b.priority_reasons.length > 0 && <details className="small"><summary>Neden üstte? (öncelik {b.priority_score})</summary><ul>{b.priority_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul></details>}
              <div className="small"><strong>Telefon:</strong> {b.phone ?? <Unverified />} · <AnalysisBadge business={b} /></div>
              <div className="small" style={{ marginTop: 4 }}><CrmCardControl business={b} onChanged={(state) => onCrmChanged(b.id, state)} /></div>
            </div>
            <div className="today-actions">
              {tel && <a className="qa-btn" href={tel}>📞 Ara</a>}
              {wa && <a className="qa-btn" href={wa} target="_blank" rel="noreferrer">💬 WhatsApp</a>}
              <a className="qa-btn" href={b.maps_url ?? b.maps_search_url} target="_blank" rel="noreferrer">📍 Google Maps</a>
              <Link className="qa-btn" href={`/businesses/${b.id}`} onClick={markLeavingList}>Detaya Git →</Link>
            </div>
          </div>
        );
      })}
    </section>
  );
}
