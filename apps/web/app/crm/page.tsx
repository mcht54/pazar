"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Business, CrmList } from "@/lib/types";
import { AnalysisBadge } from "../_components/sales";
import { CRM_DOTS, CRM_STAGES, crmPatch, FOLLOW_UP_STATE_LABELS, formatFollowUp, formatIstanbul, formatTL } from "../_components/labels";
import { QuickActions } from "../_components/sales-ops";
import { patchStoredBusiness, usePersistentState, useSessionReady } from "../_components/search-store";
import { useAuth } from "../_components/auth";

const SORTS = [
  { value: "last_action", label: "Son işlem tarihi (yeni → eski)" },
  { value: "stage", label: "CRM durumu (önce Takip Bekliyor)" },
  { value: "follow_up", label: "Takip tarihi (en yakın → en uzak)" },
  { value: "score", label: "Satış fırsatı skoru (yüksek → düşük)" },
  { value: "analyzed", label: "Analiz tarihi (yeni → eski)" },
  { value: "name", label: "Firma adı (A → Z)" },
];

function shorten(text: string | null | undefined, max = 170): string {
  const clean = (text ?? "").replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max).trimEnd()}…` : clean;
}

export default function CrmPage() {
  const [stage, setStage] = usePersistentState<string>("crm.stage", "Tümü");
  const [q, setQ] = usePersistentState<string>("crm.q", "");
  const [provinceId, setProvinceId] = usePersistentState<number | null>("crm.province", null);
  const [districtId, setDistrictId] = usePersistentState<number | null>("crm.district", null);
  const [sectorId, setSectorId] = usePersistentState<number | null>("crm.sector", null);
  const [service, setService] = usePersistentState<string>("crm.service", "");
  const [sort, setSort] = usePersistentState<string>("crm.sort", "last_action");
  const [followUp, setFollowUp] = usePersistentState<string>("crm.followUp", ""); // "" = tümü · overdue | today | upcoming | none
  const [page, setPage] = useState(1);
  const [owner, setOwner] = usePersistentState<string>("crm.owner", ""); // "" = tümü · "me" = bana ait (ekleyen/son işlem yapan) · kullanıcı kimliği
  const { user: me } = useAuth();
  const ready = useSessionReady();

  const [data, setData] = useState<CrmList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [debouncedQ, setDebouncedQ] = useState(q);
  const [savingId, setSavingId] = useState<number | null>(null);

  useEffect(() => { setPage(1); }, [stage, debouncedQ, provinceId, districtId, sectorId, service, sort, owner, followUp]);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    api.getCrmList({ stage: stage === "Tümü" ? null : stage, q: debouncedQ.trim() || null, province_id: provinceId, district_id: districtId, sector_id: sectorId, service: service || null, user_id: owner === "me" ? me?.id : owner || null, follow_up: followUp || null, sort, page, page_size: 25 })
      .then((r) => { if (!cancelled) { setData(r); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [ready, stage, debouncedQ, provinceId, districtId, sectorId, service, sort, owner, followUp, page, reload, me?.id]);

  const districts = useMemo(() => (data?.facets.districts ?? []).filter((d) => provinceId === null || d.province_id === provinceId), [data, provinceId]);
  const hasFilters = stage !== "Tümü" || !!q.trim() || provinceId !== null || districtId !== null || sectorId !== null || !!service || !!owner || !!followUp;

  function clearFilters() {
    setStage("Tümü"); setQ(""); setProvinceId(null); setDistrictId(null); setSectorId(null); setService(""); setOwner(""); setFollowUp("");
  }

  async function changeStage(b: Business, next: string) {
    setSavingId(b.id);
    try {
      const state = await api.updateCrm(b.id, { stage: next });
      patchStoredBusiness(b.id, crmPatch(state));
      setReload((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="container container-wide" id="crm-page">
      <header className="page-header">
        <h1>📋 CRM</h1>
        <p className="lead">CRM&apos;e aldığınız tüm firmalar tek yerde. Analiz edilmiş olmak firmayı CRM&apos;e otomatik eklemez; firmaları arama sonuçlarından veya firma detayından “➕ CRM&apos;e Ekle” ile alırsınız.</p>
        <p style={{ margin: 0 }}><strong data-testid="crm-count">Toplam CRM Kaydı: {data ? data.total : "…"}</strong></p>
      </header>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="chips" role="tablist" aria-label="CRM durumu" style={{ marginBottom: 12 }}>
        <button className={`chip ${stage === "Tümü" ? "active" : ""}`} onClick={() => setStage("Tümü")}>Tümü{data ? ` (${data.total})` : ""}</button>
        {CRM_STAGES.map((s) => (
          <button key={s} className={`chip ${stage === s ? "active" : ""}`} data-stage={s} onClick={() => setStage(s)}>
            {CRM_DOTS[s]} {s}{data ? ` (${data.counts[s] ?? 0})` : ""}
          </button>
        ))}
      </div>

      <div className="card">
        <div className="form-row" style={{ marginBottom: 0 }}>
          <div className="form-field" style={{ minWidth: 240 }}>
            <label htmlFor="crm-q">Ara (firma, telefon, adres, not)</label>
            <input id="crm-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Örn. işitme, 0532, Serdivan…" />
          </div>
          <div className="form-field narrow">
            <label htmlFor="crm-il">İl</label>
            <select id="crm-il" value={provinceId ?? ""} onChange={(e) => { setProvinceId(e.target.value ? Number(e.target.value) : null); setDistrictId(null); }}>
              <option value="">Tüm iller</option>
              {data?.facets.provinces.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="form-field narrow">
            <label htmlFor="crm-ilce">İlçe</label>
            <select id="crm-ilce" value={districtId ?? ""} onChange={(e) => setDistrictId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Tüm ilçeler</option>
              {districts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="crm-sektor">Sektör</label>
            <select id="crm-sektor" value={sectorId ?? ""} onChange={(e) => setSectorId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Tüm sektörler</option>
              {data?.facets.sectors.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="crm-hizmet">Önerilen hizmet</label>
            <select id="crm-hizmet" value={service} onChange={(e) => setService(e.target.value)}>
              <option value="">Tüm hizmetler</option>
              {data?.facets.services.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="crm-personel">Personel</label>
            <select id="crm-personel" value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">Tüm kayıtlar</option>
              <option value="me">👤 Bana ait (ekleyen / son işlem)</option>
              {data?.facets.users.filter((u) => u.id !== me?.id).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="crm-takip">Takip</label>
            <select id="crm-takip" value={followUp} onChange={(e) => setFollowUp(e.target.value)}>
              <option value="">Tümü</option>
              <option value="overdue">⏰ Gecikmiş</option>
              <option value="today">📅 Bugün</option>
              <option value="upcoming">🗓️ Yaklaşan</option>
              <option value="none">Takibi olmayan</option>
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="crm-sirala">Sıralama</label>
            <select id="crm-sirala" value={sort} onChange={(e) => setSort(e.target.value)}>
              {SORTS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          {hasFilters && <button className="secondary" onClick={clearFilters}>✕ Filtreleri temizle</button>}
        </div>
      </div>

      {data && <p className="muted small" data-testid="crm-filtered">{data.filtered_total} kayıt gösteriliyor{hasFilters ? ` (toplam ${data.total})` : ""}.</p>}
      {!data && !error && <p className="muted">Yükleniyor…</p>}
      {data && data.total === 0 && (
        <div className="card">
          <p><strong>CRM&apos;de henüz firma yok.</strong></p>
          <p className="muted">Analiz ettiğiniz bir firmayı CRM&apos;e almak için ana sayfada kartındaki “➕ CRM&apos;e Ekle” düğmesini ya da firma detayındaki CRM alanını kullanın.</p>
          <Link className="qa-btn" href="/">Ana sayfaya git</Link>
        </div>
      )}
      {data && data.total > 0 && data.filtered_total === 0 && <p className="muted">Bu filtrelere uyan CRM kaydı yok.</p>}

      {data?.items.map((b) => {
        return (
          <article className="card crm-item" key={b.id} data-crm-id={b.id}>
            <div className="crm-item-head">
              <div>
                <h3 style={{ fontSize: 17 }}><Link href={`/businesses/${b.id}`}>{b.name}</Link></h3>
                <p className="muted small" style={{ margin: "2px 0 0" }}>
                  {b.sector_name} · {b.province_name ?? "—"}{b.district_name ? ` / ${b.district_name}` : ""} · {b.phone ?? <span className="unverified">Telefon doğrulanamadı</span>}
                </p>
              </div>
              <div className="crm-item-stage">
                <label className="label-cap" htmlFor={`stage-${b.id}`}>CRM durumu</label>
                <select id={`stage-${b.id}`} value={b.crm_stage} disabled={savingId === b.id} onChange={(e) => changeStage(b, e.target.value)}>
                  {CRM_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>

            <dl className="crm-facts">
              <div><dt>Analiz tarihi</dt><dd><AnalysisBadge business={b} /></dd></div>
              <div><dt>Son işlem</dt><dd data-testid="crm-last-action">{formatIstanbul(b.crm_updated_at ?? b.crm_added_at)}<div className="small muted">{b.crm_last_action ?? ""}{b.crm_updated_by_name ? ` · ${b.crm_updated_by_name}` : ""}</div></dd></div>
              <div><dt>CRM'e ekleyen</dt><dd>{b.crm_added_by_name ?? "—"}</dd></div>
              <div><dt>Satış fırsatı skoru</dt><dd>{b.sales_score !== null ? <span className={`score-pill ${b.sales_score >= 45 ? "score-high" : b.sales_score >= 20 ? "score-mid" : ""}`}>{b.sales_score}/100</span> : <span className="unverified">Analiz edilmedi</span>}</dd></div>
              <div><dt>Önerilen Mchttasarım hizmeti</dt><dd>{b.primary_service ?? <span className="unverified">Kanıta dayalı öneri yok</span>}</dd></div>
              <div><dt>Sorumlu personel</dt><dd data-testid="crm-card-owner">{b.crm_owner_name ?? "—"}</dd></div>
              <div><dt>Sonraki takip</dt><dd data-testid="crm-card-follow-up">{b.next_follow_up_at ? <>{formatFollowUp(b.next_follow_up_at)} {b.follow_up_state && <span className={`fu-badge fu-${b.follow_up_state}`}>{FOLLOW_UP_STATE_LABELS[b.follow_up_state]}</span>}</> : "—"}</dd></div>
              <div><dt>Son görüşme</dt><dd>{b.last_contact_at ? formatIstanbul(b.last_contact_at) : "—"}</dd></div>
              <div><dt>İlgilenilen hizmet</dt><dd>{b.interested_service ?? "—"}</dd></div>
              <div><dt>Teklif tutarı</dt><dd>{formatTL(b.offer_amount)}</dd></div>
              <div><dt>Satış tutarı</dt><dd>{b.crm_stage === "Kazanıldı" ? (b.sale_amount != null ? formatTL(b.sale_amount) : <span className="unverified">Tutar girilmedi</span>) : "—"}</dd></div>
              {b.crm_stage === "Kaybedildi" && <div><dt>Kaybedilme nedeni</dt><dd>{b.lost_reason ?? <span className="unverified">Girilmedi</span>}</dd></div>}
            </dl>

            {b.sales_note && <p className="small crm-sales-note"><strong>Kısa satış notu:</strong> {shorten(b.sales_note)}</p>}
            {b.staff_note && <p className="small crm-own-note"><strong>CRM notu:</strong> {shorten(b.staff_note, 260)}</p>}

            <QuickActions business={b} />
            <div className="quick-actions" style={{ margin: "6px 0 0" }}>
              <Link className="qa-btn" href={`/businesses/${b.id}#crm-sales-section`}>📅 Takip / 📝 Not / 💼 Teklif · Satış</Link>
              <Link className="qa-btn" href={`/businesses/${b.id}`}>Firma detayına git →</Link>
            </div>
          </article>
        );
      })}

      {data && data.pages > 1 && (
        <nav className="pager" aria-label="Sayfalama" id="crm-pager">
          <button className="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>← Önceki</button>
          <span data-testid="crm-page-info">Sayfa {data.page} / {data.pages} · {data.filtered_total} kayıt</span>
          <button className="secondary" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>Sonraki →</button>
        </nav>
      )}
    </div>
  );
}
