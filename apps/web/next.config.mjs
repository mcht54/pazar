import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Tarayıcı API'ye aynı kökenden `/api/...` ile gider. Üretimde Nginx `/api`'yi doğrudan API'ye yönlendirir (tercih edilen yol);
// istek yine de Next.js'e ulaşırsa (Nginx'siz çalıştırma, yanlış yönlendirme, `docker compose up`) burada API'ye aktarılır.
// Hedef `next build` sırasında sabitlenir: Docker'da http://api:8000 (apps/web/Dockerfile), yerelde varsayılan localhost:8000.
const apiInternalUrl = (process.env.API_INTERNAL_URL || "http://localhost:8000").replace(/\/+$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Depo kökünde ayrı bir package-lock.json var; Next.js'in yanlış çalışma kökü seçmemesi için sabitlenir.
  turbopack: { root: here },
  agentRules: false,
  // HTML sayfaları her açılışta doğrulanır: dağıtımdan sonra tarayıcı/CDN eski sayfayı (ve eski JS paketine giden bağlantıları) tutmasın.
  // `/_next/static/*` içerik özetli (hash'li) dosyalardır, Next.js bunları zaten kalıcı önbelleğe alır; `/api` API'nin kendi başlıklarını kullanır.
  async headers() {
    return [{ source: "/((?!_next/static|_next/image|api/).*)", headers: [{ key: "Cache-Control", value: "no-cache, must-revalidate" }] }];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` }];
  },
};

export default nextConfig;
