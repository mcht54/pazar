"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Business, DiscoveryJob, Region, Sector } from "@/lib/types";

const STATUS_LABELS: Record<string, string> = {
  pending: "Bekliyor",
  running: "Çalışıyor",
  completed: "Tamamlandı",
  partial: "Kısmen tamamlandı",
  failed: "Başarısız",
};

export default function HomePage() {
  const [regions, setRegions] = useState<Region[]>([]);
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [provinceId, setProvinceId] = useState<number | null>(null);
  const [districtId, setDistrictId] = useState<number | null>(null);
  const [sectorId, setSectorId] = useState<number | null>(null);
  const [targetCount, setTargetCount] = useState(10);

  const [job, setJob] = useState<DiscoveryJob | null>(null);
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [bulkMessage, setBulkMessage] = useState<string | null>(null);

  useEffect(() => {
    api.getRegions().then(setRegions).catch((e) => setError(e.message));
    api.getSectors().then(setSectors).catch((e) => setError(e.message));
  }, []);

  const provinces = regions.filter((r) => r.level === "il");
  const districts = regions.filter((r) => r.level === "ilce" && r.parent_region_id === provinceId);
  const effectiveRegionId = districtId ?? provinceId;

  useEffect(() => {
    if (!job || job.status === "completed" || job.status === "partial" || job.status === "failed") return;
    const interval = setInterval(async () => {
      const updated = await api.getDiscoveryJob(job.id);
      setJob(updated);
      if (updated.status !== "pending" && updated.status !== "running") {
        clearInterval(interval);
        const results = await api.getBusinesses({ region_id: updated.region_id, sector_id: updated.sector_id });
        setBusinesses(results);
      }
    }, 1200);
    return () => clearInterval(interval);
  }, [job]);

  async function handleDiscover() {
    setError(null);
    setBulkMessage(null);
    if (!effectiveRegionId || !sectorId) {
      setError("Bölge ve sektör seçmelisiniz.");
      return;
    }
    try {
      const created = await api.createDiscoveryJob(effectiveRegionId, sectorId, targetCount);
      setJob(created);
      setBusinesses([]);
      setSelectedIds(new Set());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function toggleSelected(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleAnalyzeSelected() {
    setBulkMessage(null);
    try {
      const jobs = await api.analyzeBulk({ business_ids: Array.from(selectedIds) });
      setBulkMessage(`${jobs.length} işletme için analiz başlatıldı.`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleAnalyzeTop10() {
    setBulkMessage(null);
    try {
      const jobs = await api.analyzeBulk({ top_n: 10 });
      setBulkMessage(`İlk ${jobs.length} işletme için analiz başlatıldı.`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const isRunningJob = job && (job.status === "pending" || job.status === "running");
  const progressPct = job ? Math.min(100, Math.round(((job.found_new + job.found_existing) / job.target_count) * 100)) : 0;

  return (
    <main className="container">
      <h1>Mchttasarım Marketing OS</h1>
      <p className="muted">Bölge ve sektör seçip potansiyel müşterileri keşfedin.</p>

      <div className="card">
        <div className="form-row">
          <div className="form-field">
            <label>Bölge (İl)</label>
            <select
              value={provinceId ?? ""}
              onChange={(e) => {
                setProvinceId(e.target.value ? Number(e.target.value) : null);
                setDistrictId(null);
              }}
            >
              <option value="">Seçiniz</option>
              {provinces.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </div>

          <div className="form-field">
            <label>İlçe (opsiyonel)</label>
            <select value={districtId ?? ""} onChange={(e) => setDistrictId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Tüm il geneli</option>
              {districts.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </div>

          <div className="form-field">
            <label>Sektör</label>
            <select value={sectorId ?? ""} onChange={(e) => setSectorId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Seçiniz</option>
              {sectors.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>

          <div className="form-field">
            <label>İşletme sayısı</label>
            <input type="number" min={1} max={200} value={targetCount} onChange={(e) => setTargetCount(Number(e.target.value))} />
          </div>

          <button className="primary" onClick={handleDiscover} disabled={!!isRunningJob}>
            {isRunningJob ? "Taranıyor..." : "Potansiyel Müşterileri Bul"}
          </button>
        </div>

        {error && <p className="error">{error}</p>}

        {job && (
          <div>
            <div className="progress-bar">
              <div className="progress-bar-fill" style={{ width: `${progressPct}%` }} />
            </div>
            <p className="muted">
              Durum: <strong>{STATUS_LABELS[job.status] ?? job.status}</strong> — yeni: {job.found_new}, mevcut: {job.found_existing}
              {job.item_errors.length > 0 && `, hata: ${job.item_errors.length}`}
            </p>
            {job.item_errors.length > 0 && (
              <ul className="muted">
                {job.item_errors.map((e, i) => (
                  <li key={i}>{e.external_ref}: {e.reason}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {businesses.length > 0 && (
        <>
          <div className="form-row" style={{ justifyContent: "space-between" }}>
            <h2 style={{ margin: 0 }}>Sonuçlar ({businesses.length})</h2>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="secondary" onClick={handleAnalyzeSelected} disabled={selectedIds.size === 0}>
                Seçilenleri Analiz Et ({selectedIds.size})
              </button>
              <button className="secondary" onClick={handleAnalyzeTop10}>İlk 10&apos;u Analiz Et</button>
            </div>
          </div>
          {bulkMessage && <p className="muted">{bulkMessage}</p>}

          {businesses.some((b) => b.is_demo_data) && (
            <p className="demo-badge">DEMO DATA — Gerçek Google verisi değildir</p>
          )}

          <table>
            <thead>
              <tr>
                <th></th>
                <th>İşletme</th>
                <th>Adres</th>
                <th>Telefon</th>
                <th>Website</th>
                <th>Rating</th>
                <th>Yorum</th>
                <th>Kaynak</th>
                <th>Analiz</th>
              </tr>
            </thead>
            <tbody>
              {businesses.map((b) => (
                <tr key={b.id}>
                  <td><input type="checkbox" checked={selectedIds.has(b.id)} onChange={() => toggleSelected(b.id)} /></td>
                  <td><Link href={`/businesses/${b.id}`}>{b.name}</Link></td>
                  <td>{b.address ?? "-"}</td>
                  <td>{b.phone ?? "-"}</td>
                  <td>{b.website ?? "-"}</td>
                  <td>{b.google_rating ?? "-"}</td>
                  <td>{b.google_review_count ?? "-"}</td>
                  <td>{b.is_demo_data ? "DEMO" : b.discovery_source}</td>
                  <td>{b.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
