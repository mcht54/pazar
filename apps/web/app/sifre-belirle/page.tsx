"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

function SetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const [status, setStatus] = useState<"checking" | "valid" | "invalid" | "done">("checking");
  const [info, setInfo] = useState<{ purpose?: string; name?: string | null; message?: string }>({});
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) { setStatus("invalid"); setInfo({ message: "Bağlantıda token bulunamadı." }); return; }
    api.checkResetToken(token)
      .then((r) => { setInfo(r); setStatus(r.valid ? "valid" : "invalid"); })
      .catch((e) => { setInfo({ message: e.message }); setStatus("invalid"); });
  }, [token]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== again) { setError("Şifreler aynı değil."); return; }
    setBusy(true); setError(null);
    try {
      await api.setPassword(token, password);
      setStatus("done");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="card login-card" id="set-password-card">
        <h1>🔐 Şifre Belirle</h1>
        {status === "checking" && <p className="muted">Bağlantı kontrol ediliyor…</p>}
        {status === "invalid" && (
          <>
            <p className="error" role="alert" id="token-invalid">{info.message ?? "Bağlantı geçersiz, süresi dolmuş ya da daha önce kullanılmış."}</p>
            <p className="small"><Link href="/sifremi-unuttum">Yeni bağlantı iste</Link> · <Link href="/login">Giriş</Link></p>
          </>
        )}
        {status === "done" && (
          <>
            <p className="crm-ok" role="status" id="password-set-ok">✓ Şifreniz belirlendi. Şimdi giriş yapabilirsiniz.</p>
            <Link className="qa-btn" href="/login">Giriş Yap</Link>
          </>
        )}
        {status === "valid" && (
          <form onSubmit={submit}>
            <p className="muted small">{info.name ? `${info.name}, ` : ""}{info.purpose === "invite" ? "hesabınız için bir şifre belirleyin." : "yeni şifrenizi belirleyin."} En az 8 karakter; en az bir harf ve bir rakam.</p>
            <div className="form-field">
              <label htmlFor="new-pw">Yeni şifre</label>
              <input id="new-pw" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
            </div>
            <div className="form-field">
              <label htmlFor="new-pw2">Yeni şifre (tekrar)</label>
              <input id="new-pw2" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
            </div>
            {error && <p className="error" role="alert">{error}</p>}
            <button className="primary" type="submit" disabled={busy || !password || !again}>{busy ? "Kaydediliyor…" : "Şifreyi Kaydet"}</button>
          </form>
        )}
      </div>
    </div>
  );
}

export default function SetPasswordPage() {
  return <Suspense fallback={<div className="container"><p className="muted">Yükleniyor…</p></div>}><SetPasswordForm /></Suspense>;
}
