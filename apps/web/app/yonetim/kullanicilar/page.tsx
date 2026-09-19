"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AdminUsers, AuthUser } from "@/lib/types";
import { formatIstanbul } from "../../_components/labels";
import { Modal } from "../../_components/sales";
import { useAuth } from "../../_components/auth";

const EMPTY = { name: "", email: "", username: "", role: "calisan", password: "", is_active: true, send_invite: false };

function CopyBox({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="temp-pw">
      <code id="temp-password">{text}</code>
      <button className="secondary" onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); } catch { setDone(false); } }}>{done ? "✓ Kopyalandı" : "📋 Kopyala"}</button>
    </div>
  );
}

export default function UsersPage() {
  const { user: me } = useAuth();
  const [data, setData] = useState<AdminUsers | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [editing, setEditing] = useState<AuthUser | null>(null);
  const [tempShown, setTempShown] = useState<{ title: string; password: string; note: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(() => api.listUsers().then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const created = await api.createUser({ ...form, password: form.send_invite ? undefined : form.password || undefined });
      setCreating(false); setForm({ ...EMPTY });
      if (form.send_invite) {
        // Davet: şifre gösterilmez/gönderilmez; kullanıcıya şifre belirleme bağlantısı e-postalanır.
        setMessage(created.invite_sent ? `✓ ${created.name} oluşturuldu; ${created.email} adresine şifre belirleme bağlantısı gönderildi.` : `⚠️ ${created.name} oluşturuldu ancak bağlantı gönderilemedi: ${created.invite_error}. “Bağlantı Gönder” ile yeniden deneyin.`);
      } else if (created.temporary_password) {
        setTempShown({ title: `${created.name} oluşturuldu`, password: created.temporary_password, note: "Bu geçici şifre yalnızca bir kez gösterilir. Kullanıcı ilk girişte şifresini değiştirmek zorundadır." });
        setMessage(`✓ ${created.name} oluşturuldu.`);
      }
      await load();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setBusy(true); setError(null);
    try {
      await api.updateUser(editing.id, { name: editing.name, email: editing.email, username: editing.username ?? undefined, role: editing.role });
      setEditing(null); setMessage("✓ Kullanıcı güncellendi.");
      await load();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  async function toggleActive(u: AuthUser) {
    setError(null);
    try {
      await api.updateUser(u.id, { is_active: !u.is_active });
      setMessage(`✓ ${u.name} ${u.is_active ? "pasifleştirildi (giriş yapamaz; eski kayıtları korunur)" : "aktifleştirildi"}.`);
      await load();
    } catch (err) { setError((err as Error).message); }
  }

  async function sendLink(u: AuthUser) {
    setError(null); setMessage(null);
    try {
      setMessage(`✓ ${(await api.sendPasswordLink(u.id)).message}`);
    } catch (err) { setError((err as Error).message); }
  }

  async function reset(u: AuthUser) {
    if (!window.confirm(`${u.name} için şifre sıfırlansın mı? Kullanıcının açık oturumları kapanır.`)) return;
    setError(null);
    try {
      const r = await api.resetPassword(u.id);
      setTempShown({ title: `${u.name} — yeni geçici şifre`, password: r.temporary_password, note: "Mevcut şifre görülemez. Bu geçici şifre yalnızca bir kez gösterilir; kullanıcı ilk girişte değiştirmek zorundadır." });
    } catch (err) { setError((err as Error).message); }
  }

  return (
    <div className="container container-wide">
      <header className="page-header">
        <h1>👥 Kullanıcı Yönetimi</h1>
        <p className="lead">Kullanıcı oluşturun, rol atayın, pasifleştirin ve şifre sıfırlayın. Kullanıcılar silinmez; pasifleştirilir — eski CRM ve analiz kayıtları korunur.</p>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {message && <p className="notice notice-ok" role="status">{message}</p>}
      <div className="actions" style={{ marginBottom: 12 }}>
        <button className="primary" onClick={() => { setCreating(true); setError(null); setMessage(null); }}>➕ Yeni Kullanıcı</button>
      </div>
      <div className="card table-scroll">
        <table id="users-table">
          <thead><tr><th>Ad Soyad</th><th>E-posta</th><th>Rol</th><th>Durum</th><th>Son giriş</th><th>Oluşturulma</th><th>İşlemler</th></tr></thead>
          <tbody>
            {data?.items.map((u) => (
              <tr key={u.id} data-user-id={u.id} className={u.is_active ? "" : "row-inactive"}>
                <td><strong>{u.name}</strong><div className="muted small">{u.username ?? ""}</div></td>
                <td>{u.email}</td>
                <td>{u.role_icon} {u.role_label}</td>
                <td>{u.is_active ? <span className="badge status-ok">Aktif</span> : <span className="badge status-unknown">Pasif</span>}{u.must_change_password && <div className="muted small">Şifre değişimi bekliyor</div>}</td>
                <td>{u.last_login_at ? formatIstanbul(u.last_login_at) : <span className="muted">Hiç giriş yapmadı</span>}</td>
                <td>{formatIstanbul(u.created_at)}</td>
                <td>
                  <div className="row-actions">
                    <button className="secondary" onClick={() => { setEditing({ ...u }); setError(null); }}>✏️ Düzenle</button>
                    <button className="secondary" onClick={() => reset(u)}>🔑 Şifre Sıfırla</button>
                    {u.is_active && <button className="secondary" onClick={() => sendLink(u)} title="Kullanıcıya e-postayla tek kullanımlık şifre belirleme bağlantısı gönderir">✉️ Bağlantı Gönder</button>}
                    {u.id !== me?.id && <button className="secondary" onClick={() => toggleActive(u)}>{u.is_active ? "⏸ Pasifleştir" : "▶ Aktifleştir"}</button>}
                  </div>
                </td>
              </tr>
            ))}
            {!data && <tr><td colSpan={7} className="muted">Yükleniyor…</td></tr>}
          </tbody>
        </table>
      </div>

      {creating && (
        <Modal title="➕ Yeni Kullanıcı" onClose={() => setCreating(false)}>
          <form onSubmit={create} aria-label="Yeni kullanıcı formu">
            <div className="form-field"><label htmlFor="nu-name">Ad Soyad</label><input id="nu-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></div>
            <div className="form-field"><label htmlFor="nu-email">E-posta</label><input id="nu-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></div>
            <div className="form-field"><label htmlFor="nu-user">Kullanıcı adı</label><input id="nu-user" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required placeholder="küçük harf, rakam, . - _" /></div>
            <div className="form-field"><label htmlFor="nu-role">Rol</label>
              <select id="nu-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {data?.roles.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
              </select></div>
            <label className="check"><input id="nu-invite" type="checkbox" checked={form.send_invite} onChange={(e) => setForm({ ...form, send_invite: e.target.checked })} /> Şifre belirleme bağlantısını e-postayla gönder (düz şifre gönderilmez; E-posta Ayarları aktif olmalı)</label>
            {!form.send_invite && <div className="form-field"><label htmlFor="nu-pw">Geçici şifre (boş bırakırsanız güvenli bir şifre üretilir)</label><input id="nu-pw" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="off" /></div>}
            <label className="check"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Aktif</label>
            {error && <p className="error" role="alert">{error}</p>}
            <div className="guide-actions"><button className="primary" type="submit" disabled={busy}>{busy ? "Oluşturuluyor…" : "Kullanıcıyı Oluştur"}</button><button type="button" className="secondary" onClick={() => setCreating(false)}>Vazgeç</button></div>
          </form>
        </Modal>
      )}

      {editing && (
        <Modal title={`✏️ ${editing.name} — Düzenle`} onClose={() => setEditing(null)}>
          <form onSubmit={saveEdit} aria-label="Kullanıcı düzenleme formu">
            <div className="form-field"><label htmlFor="eu-name">Ad Soyad</label><input id="eu-name" value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} required /></div>
            <div className="form-field"><label htmlFor="eu-email">E-posta</label><input id="eu-email" type="email" value={editing.email} onChange={(e) => setEditing({ ...editing, email: e.target.value })} required /></div>
            <div className="form-field"><label htmlFor="eu-user">Kullanıcı adı</label><input id="eu-user" value={editing.username ?? ""} onChange={(e) => setEditing({ ...editing, username: e.target.value })} required /></div>
            <div className="form-field"><label htmlFor="eu-role">Rol</label>
              <select id="eu-role" value={editing.role} disabled={editing.id === me?.id} onChange={(e) => setEditing({ ...editing, role: e.target.value as AuthUser["role"] })}>
                {data?.roles.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
              </select></div>
            {error && <p className="error" role="alert">{error}</p>}
            <div className="guide-actions"><button className="primary" type="submit" disabled={busy}>Kaydet</button><button type="button" className="secondary" onClick={() => setEditing(null)}>Vazgeç</button></div>
          </form>
        </Modal>
      )}

      {tempShown && (
        <Modal title={`🔑 ${tempShown.title}`} onClose={() => setTempShown(null)}>
          <p>Geçici şifre:</p>
          <CopyBox text={tempShown.password} />
          <p className="muted small">{tempShown.note}</p>
          <div className="guide-actions"><button className="primary" onClick={() => setTempShown(null)}>Tamam</button></div>
        </Modal>
      )}
    </div>
  );
}
