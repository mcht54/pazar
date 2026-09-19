"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { formatIstanbul } from "../_components/labels";
import { useAuth } from "../_components/auth";

export default function ProfilePage() {
  const { user, setUser, logout } = useAuth();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (!user) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    if (next !== again) {
      setMessage({ ok: false, text: "Yeni şifre ve tekrarı aynı değil." });
      return;
    }
    setBusy(true);
    try {
      const updated = await api.changePassword(current, next);
      setUser(updated);
      setCurrent(""); setNext(""); setAgain("");
      setMessage({ ok: true, text: "✓ Şifreniz değiştirildi." });
      if (user?.must_change_password) router.replace("/");
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container">
      <header className="page-header">
        <h1>👤 Profil</h1>
      </header>
      <div className="card">
        <table className="kv"><tbody>
          <tr><th>Ad Soyad</th><td>{user.name}</td></tr>
          <tr><th>E-posta</th><td>{user.email}</td></tr>
          <tr><th>Kullanıcı adı</th><td>{user.username ?? "—"}</td></tr>
          <tr><th>Rol</th><td>{user.role_icon} {user.role_label}</td></tr>
          <tr><th>Son giriş</th><td>{formatIstanbul(user.last_login_at)}</td></tr>
        </tbody></table>
      </div>
      <form className="card" onSubmit={submit} aria-label="Şifre değiştir" id="password-form">
        <h2 style={{ marginTop: 0 }}>🔑 Şifre Değiştir</h2>
        {user.must_change_password && <p className="notice notice-warn" role="alert">Geçici şifreyle giriş yaptınız. Devam etmek için yeni bir şifre belirlemelisiniz.</p>}
        <div className="form-row">
          <div className="form-field"><label htmlFor="pw-current">Mevcut şifre</label><input id="pw-current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required /></div>
          <div className="form-field"><label htmlFor="pw-new">Yeni şifre</label><input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required /></div>
          <div className="form-field"><label htmlFor="pw-again">Yeni şifre (tekrar)</label><input id="pw-again" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required /></div>
        </div>
        <p className="muted small">En az 8 karakter; en az bir harf ve bir rakam içermeli.</p>
        {message && <p className={message.ok ? "crm-ok" : "error"} role="status">{message.text}</p>}
        <div className="actions">
          <button className="primary" type="submit" disabled={busy}>{busy ? "Kaydediliyor…" : "Şifreyi Değiştir"}</button>
          {!user.must_change_password && <button type="button" className="secondary" onClick={async () => { await logout(); router.replace("/login"); }}>🚪 Çıkış Yap</button>}
        </div>
      </form>
    </div>
  );
}
