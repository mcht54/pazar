"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ActivityList, AdminUsers } from "@/lib/types";
import { formatIstanbul } from "../../_components/labels";
import Link from "next/link";

export default function ActivityPage() {
  const [data, setData] = useState<ActivityList | null>(null);
  const [users, setUsers] = useState<AdminUsers | null>(null);
  const [userId, setUserId] = useState("");
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const LIMIT = 50;

  useEffect(() => { api.listUsers().then(setUsers).catch(() => {}); }, []);
  useEffect(() => {
    api.getActivity({ user_id: userId, action, limit: LIMIT, offset }).then((r) => { setData(r); setError(null); }).catch((e) => setError(e.message));
  }, [userId, action, offset]);

  return (
    <div className="container container-wide">
      <header className="page-header">
        <h1>🕘 Personel Aktiviteleri</h1>
        <p className="lead">Kim, ne zaman, hangi firmada ne yaptı. Kayıtlar yalnızca eklenir; silinmez.</p>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="card"><div className="form-row" style={{ marginBottom: 0 }}>
        <div className="form-field"><label htmlFor="act-user">Personel</label>
          <select id="act-user" value={userId} onChange={(e) => { setUserId(e.target.value); setOffset(0); }}>
            <option value="">Tümü</option>{users?.items.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select></div>
        <div className="form-field"><label htmlFor="act-action">İşlem</label>
          <select id="act-action" value={action} onChange={(e) => { setAction(e.target.value); setOffset(0); }}>
            <option value="">Tümü</option>{data?.actions.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}
          </select></div>
      </div></div>
      <div className="card table-scroll">
        <table id="activity-table">
          <thead><tr><th>Tarih / saat</th><th>Personel</th><th>İşlem</th><th>Firma</th><th>Ayrıntı</th></tr></thead>
          <tbody>
            {data?.items.map((a) => (
              <tr key={a.id}>
                <td>{formatIstanbul(a.created_at)}</td><td>{a.user_name}</td><td>{a.action_label}</td>
                <td>{a.business_id ? <Link href={`/businesses/${a.business_id}`}>{a.business_name ?? `#${a.business_id}`}</Link> : "—"}</td>
                <td className="small">{a.detail ?? "—"}</td>
              </tr>
            ))}
            {data && data.items.length === 0 && <tr><td colSpan={5} className="muted">Kayıt yok.</td></tr>}
            {!data && <tr><td colSpan={5} className="muted">Yükleniyor…</td></tr>}
          </tbody>
        </table>
        {data && data.total > LIMIT && (
          <div className="actions">
            <button className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>← Önceki</button>
            <span className="muted small">{offset + 1}–{Math.min(offset + LIMIT, data.total)} / {data.total}</span>
            <button className="secondary" disabled={offset + LIMIT >= data.total} onClick={() => setOffset(offset + LIMIT)}>Sonraki →</button>
          </div>
        )}
      </div>
    </div>
  );
}
