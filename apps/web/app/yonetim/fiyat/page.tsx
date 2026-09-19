"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ServicePriceRow } from "@/lib/types";
import { formatTL } from "../../_components/labels";

type Draft = { min: string; max: string; def: string; active: boolean };

const toDraft = (r: ServicePriceRow): Draft => ({ min: r.min_price?.toString() ?? "", max: r.max_price?.toString() ?? "", def: r.default_price?.toString() ?? "", active: r.is_active });

export default function ServicePricesPage() {
  const [rows, setRows] = useState<ServicePriceRow[] | null>(null);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [meta, setMeta] = useState({ notPriced: "Fiyatlandırma yapılmadı", disclaimer: "" });
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState<number | null>(null);

  const load = useCallback(() => api.getServicePrices().then((r) => {
    setRows(r.items);
    setDrafts(Object.fromEntries(r.items.map((i) => [i.service_id, toDraft(i)])));
    setMeta({ notPriced: r.not_priced_label, disclaimer: r.disclaimer });
  }).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  async function save(row: ServicePriceRow) {
    const d = drafts[row.service_id];
    setSaving(row.service_id); setError(null); setMessage(null);
    try {
      const saved = await api.saveServicePrice(row.service_id, { min_price: d.min || null, max_price: d.max || null, default_price: d.def || null, is_active: d.active });
      setRows((rs) => rs?.map((r) => (r.service_id === saved.service_id ? saved : r)) ?? null);
      setDrafts((ds) => ({ ...ds, [saved.service_id]: toDraft(saved) }));
      setMessage(`✓ ${saved.service_name}: fiyat aralığı kaydedildi.`);
    } catch (e) { setError((e as Error).message); } finally { setSaving(null); }
  }

  const set = (id: number, patch: Partial<Draft>) => setDrafts((ds) => ({ ...ds, [id]: { ...ds[id], ...patch } }));

  return (
    <div className="container container-wide">
      <header className="page-header">
        <h1>💰 Hizmet ve Fiyat Ayarları</h1>
        <p className="lead">Satış planındaki “tahmini değer” ve “önerilen paket” bu fiyat aralıklarından hesaplanır. Fiyat girmediğiniz hizmetler için sistem “{meta.notPriced}” der; hiçbir fiyat kodda sabit değildir.</p>
        <p className="muted small">{meta.disclaimer}</p>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {message && <p className="crm-ok" role="status" id="price-message">{message}</p>}
      {!rows && !error && <p className="muted">Yükleniyor…</p>}
      {rows && (
        <div className="card table-wrap">
          <table className="data-table" id="price-table">
            <thead><tr><th>Hizmet</th><th>En düşük (TL)</th><th>En yüksek (TL)</th><th>Varsayılan (TL)</th><th>Aktif</th><th>Durum</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => {
                const d = drafts[r.service_id];
                if (!d) return null;
                return (
                  <tr key={r.service_id} data-service={r.service_name}>
                    <td><strong>{r.service_name}</strong></td>
                    <td><input aria-label={`${r.service_name} en düşük fiyat`} inputMode="decimal" value={d.min} onChange={(e) => set(r.service_id, { min: e.target.value })} /></td>
                    <td><input aria-label={`${r.service_name} en yüksek fiyat`} inputMode="decimal" value={d.max} onChange={(e) => set(r.service_id, { max: e.target.value })} /></td>
                    <td><input aria-label={`${r.service_name} varsayılan fiyat`} inputMode="decimal" value={d.def} onChange={(e) => set(r.service_id, { def: e.target.value })} /></td>
                    <td><input type="checkbox" aria-label={`${r.service_name} aktif`} checked={d.active} onChange={(e) => set(r.service_id, { active: e.target.checked })} /></td>
                    <td className="small">{r.priced ? <span>{formatTL(r.min_price ?? r.default_price)} – {formatTL(r.max_price ?? r.default_price)}</span> : <span className="unverified">{meta.notPriced}</span>}</td>
                    <td><button className="secondary" disabled={saving !== null} onClick={() => save(r)}>{saving === r.service_id ? "…" : "Kaydet"}</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
