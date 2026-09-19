"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { AuthUser } from "@/lib/types";
import { clearSearchStore } from "./search-store";

// Oturum: sunucu tarafı (HttpOnly çerez). Sayfa yenilenince /api/auth/me ile geri yüklenir. Yetki kontrolünün asıl sınırı SUNUCUDADIR;
// buradaki `can` yalnızca menü/düğmeleri gizlemek içindir.
interface AuthValue {
  user: AuthUser | null;
  loading: boolean;
  can: (permission: string) => boolean;
  login: (identifier: string, password: string, remember?: boolean) => Promise<AuthUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setUser: (user: AuthUser | null) => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth yalnızca AuthProvider içinde kullanılabilir");
  return value;
}

const LAST_USER_KEY = "mch.lastUser";

function rememberUser(user: AuthUser | null) {
  // Başka bir kullanıcı giriş yaptıysa önceki kullanıcının arama durumu temizlenir.
  try {
    const previous = sessionStorage.getItem(LAST_USER_KEY);
    if (user && previous && previous !== String(user.id)) clearSearchStore();
    if (user) sessionStorage.setItem(LAST_USER_KEY, String(user.id));
  } catch {
    /* depolama yok */
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const setUser = useCallback((next: AuthUser | null) => {
    rememberUser(next);
    setUserState(next);
  }, []);

  const refresh = useCallback(async () => {
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [setUser]);

  useEffect(() => {
    refresh();
    const onUnauthorized = () => setUserState(null);
    const onPasswordChange = () => refresh();
    window.addEventListener("mch:unauthorized", onUnauthorized);
    window.addEventListener("mch:password-change", onPasswordChange);
    return () => {
      window.removeEventListener("mch:unauthorized", onUnauthorized);
      window.removeEventListener("mch:password-change", onPasswordChange);
    };
  }, [refresh]);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      loading,
      can: (permission) => !!user && user.permissions.includes(permission),
      login: async (identifier, password, remember = false) => {
        const u = await api.login(identifier, password, remember);
        setUser(u);
        return u;
      },
      logout: async () => {
        try {
          await api.logout();
        } finally {
          clearSearchStore();
          setUserState(null);
          try {
            sessionStorage.removeItem(LAST_USER_KEY);
          } catch {
            /* yok say */
          }
        }
      },
      refresh,
      setUser,
    }),
    [user, loading, refresh, setUser]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Korumalı alan: giriş yapmamışsa /login'e; geçici şifreyle girmişse şifre değiştirme ekranına; yönetim sayfalarında yönetici değilse engel ekranı. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const onLogin = pathname === "/login";
  const onPublic = onLogin || pathname === "/sifremi-unuttum" || pathname === "/sifre-belirle"; // giriş gerektirmeyen sayfalar
  const onProfile = pathname === "/profil";

  useEffect(() => {
    if (loading) return;
    if (!user && !onPublic) router.replace("/login");
    else if (user && onLogin) router.replace(user.must_change_password ? "/profil" : "/");
    else if (user?.must_change_password && !onProfile) router.replace("/profil");
  }, [loading, user, onLogin, onPublic, onProfile, router]);

  if (loading) return <div className="container"><p className="muted" role="status">Oturum kontrol ediliyor…</p></div>;
  if (onPublic) return <>{children}</>;
  if (!user) return null;
  if (user.must_change_password && !onProfile) return null;
  if (pathname.startsWith("/yonetim") && user.role !== "yonetici") {
    return (
      <div className="container">
        <div className="card">
          <h1>⛔ Erişim yetkiniz yok</h1>
          <p>Bu sayfa yalnızca yönetici rolündeki kullanıcılar içindir.</p>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
