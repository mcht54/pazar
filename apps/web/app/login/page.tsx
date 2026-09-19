"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "../_components/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await login(identifier.trim(), password, remember);
      router.replace(user.must_change_password ? "/profil" : "/");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit} aria-label="Giriş formu">
        <h1>🔐 Mchttasarım Satış Operasyon</h1>
        <div className="form-field">
          <label htmlFor="login-id">E-posta / Kullanıcı adı</label>
          <input id="login-id" autoComplete="username" value={identifier} onChange={(e) => setIdentifier(e.target.value)} required autoFocus />
        </div>
        <div className="form-field">
          <label htmlFor="login-pw">Şifre</label>
          <input id="login-pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        <label className="check"><input id="login-remember" type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Beni hatırla <span className="muted small">(bu tarayıcıda 30 gün)</span></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" type="submit" disabled={busy || !identifier || !password}>{busy ? "Giriş yapılıyor…" : "Giriş Yap"}</button>
        <p className="small"><Link href="/sifremi-unuttum" id="forgot-link">Şifremi unuttum</Link></p>
        <p className="muted small">Hesabınız yoksa yöneticinizle iletişime geçin.</p>
      </form>
    </div>
  );
}
