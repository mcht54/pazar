# Mchttasarım Satış Fırsatı Analiz Sistemi

Mchttasarım Reklam Ajansı için, "işletme listesi" değil **satış yapılabilecek işletmeleri ve gerekçelerini** bulan sistem.

```
ŞEHİR → İLÇE → SEKTÖR → GERÇEK İŞLETMELER → GOOGLE PROFİL ANALİZİ → WEB SİTESİ ANALİZİ
      → EKSİKLER → SATILABİLECEK HİZMETLER → SATIŞ FIRSATI (Yüksek/Orta/Düşük) → ÖNCELİKLİ MÜŞTERİLER
```

Tasarım dokümanı: [docs/plans/2026-09-18-mchttasarim-marketing-os-design.md](docs/plans/2026-09-18-mchttasarim-marketing-os-design.md).

## Temel ilke: veri uydurulmaz

Bir bilgi kaynaktan doğrulanamıyorsa ekranda **"Doğrulanamadı"** yazar; tahmini değer gerçek gibi gösterilmez.
"Doğrulanamadı" hiçbir zaman "sorun var" diye sayılmaz ve satış seviyesini etkilemez.

## Veri akışı ve kaynaklar (API anahtarsız)

```
Şehir → İlçe → Sektör → Google Haritalar'da işletme araması (gerçek işletmeler, koordinat, puan, yorum, kategori, telefon)
      → her işletme için: Google profili (tam sayfa) + Bing Haritalar + resmi web sitesi + sosyal medya → çapraz doğrulama
      → web sitesi analizi → eksikler → satılabilecek hizmet → satış fırsatı
```

**OpenStreetMap/Overpass artık kullanılmıyor.** Keşif de doğrulama da Google Haritalar'dan (gerçek bir Chromium ile, herkese açık sayfa) yapılır;
resmi Google API'si ve anahtarı gerekmez.

| Kaynak | Ne için | Durum (bu ortamda ölçüldü) |
|---|---|---|
| **Google Haritalar** | Keşif + profil: ad, koordinat (`!3d…!4d…`), puan, yorum sayısı, kategori, adres, telefon, web sitesi, çalışma saatleri, "Hakkında" (`div[role="main"]`), yorum tarihleri/işletme yanıtları, kapak fotoğrafı tarihi | Çalışıyor |
| **Bing Haritalar** | Google'dan bağımsız ikinci dizin (adres/telefon/site/konum) | Çalışıyor |
| **Resmi web sitesi** | İletişim bilgisi, SEO/teknik analiz, sosyal medya bağlantıları | Çalışıyor |
| Google Arama | Web sitesi adayı bulma | **ERİŞİLEMİYOR** — otomatik erişime CAPTCHA ("sıra dışı trafik") dönüyor; aşılmaz |
| DuckDuckGo / Brave / Mojeek | — | Bot doğrulaması/403 — kullanılamaz |
| Bing web araması | Web sitesi adayı | Erişilebilir ama küçük işletmelerde alakasız sonuç verir; yalnızca aday üretir, içerik doğrulaması şart |

Her işletme kartında **kaynak durumu** teknik olarak gösterilir: `KONTROL EDİLDİ` · `ERİŞİLEMEDİ` · `EŞLEŞME YOK` · `ATLANDI`.

### Doğrulama durumları

🟢 **DOĞRULANDI** (≥2 kaynak aynı değeri veriyor ya da eşleşmesi kesin tek yetkili kaynak) · 🟠 **ÇELİŞKİLİ** (kaynaklar farklı — manuel kontrol) ·
🔴 **BULUNAMADI** (erişilebilen kaynaklarda yok; kaynağa erişilemediği için hiç kontrol edilemediyse ayrıca "kontrol edilemedi" yazar) ·
⚪ **TEK KAYNAK** (yalnızca güvenilirliği doğrulanmamış tek kaynakta var; yalnızca eski keşif kayıtlarında görülür).

Yanlış işletmenin bilgisini bağlamamak için eşleştirme **ad (marka sözcükleri) + konum + telefon + adres** ile yapılır ve en az iki bağımsız sinyal
gerekir. Web sitesi adayları (alan adı tahmini/arama) içerikte işletme adı + telefon/adres/şehir eşleşmeden kabul edilmez. Hiçbir değer tahmin edilmez.

> **Kullanım şartları uyarısı:** Google'ın şartları otomatik erişime izin vermez. Bu yöntem düşük hacim, kaynak başına minimum bekleme, 7 günlük önbellek ve yalnızca
> kullanıcı isteğiyle çalışır; CAPTCHA/consent görülürse **durur, aşmaya çalışmaz**. Risk size aittir; resmi alternatif için `DISCOVERY_PROVIDER=google` (Places API, anahtar gerekir).

## Mimari

- **apps/api** — FastAPI backend
- **apps/web** — Next.js panel (Türkçe)
- **services/worker** — Celery worker (keşif → otomatik araştırma + analiz)
- **services/integrations/google_places** — `maps_provider.py` (Google Haritalar keşfi, varsayılan), `google_provider.py` (Places API, opsiyonel), `mock_provider.py` (sadece test)
- **services/research** — `google_maps.py`, `bing_maps.py`, `site_finder.py`, `social.py`, `crosscheck.py`, `pipeline.py` (çok kaynaklı araştırma ve çapraz doğrulama)
- **services/integrations/website_crawler** — web sitesini gerçekten açıp ölçer
- **services/rule_engine** — deterministik kontroller (`checks.py`) ve satış değerlendirmesi (`sales.py`)
- **packages/db** — modeller, Alembic, `sectors_data.py` (135 Türkçe sektör), il/ilçe veri seti

## Sektörler

135 sektör, 15 grupta (Sağlık, Güzellik, Yeme-İçme, Konaklama, Otomotiv, Emlak/İnşaat, Ev/Mobilya, Perakende, Profesyonel Hizmetler,
Reklam/Yazılım, Eğitim, Spor/Eğlence, Ulaşım, Sanayi/Toptan, Kişisel Hizmetler). **İşitme Cihazı Merkezi** dahildir. Tüm adlar Türkçedir.
Listeyi genişletmek için [packages/db/sectors_data.py](packages/db/sectors_data.py) dosyasına `(ad, grup, Türkçe arama ifadeleri)` satırı ekleyip
`python -m packages.db.seed` çalıştırmak yeterlidir. Eski adlar (örn. "Fast Food") yerinde yeniden adlandırılır, bağlı işletmeler bozulmaz.

Arama: her sektörün ilk arama ifadesi (örn. "işitme cihazı") + ilçe + il Google Haritalar'da aranır, sonuç listesi kaydırılarak istenen sayıya kadar okunur; bölge dışı ve tekrar eden kayıtlar elenir.

## Web sitesi analizi (gerçek)

Site varsa açılır ve şunlar ölçülür: erişim (DNS/404/SSL/bot koruması ayrımı), HTTPS, mobil uyumluluk işareti (viewport — **gerçek cihaz testi değildir**, öyle etiketlenir),
sayfa hızı (Google PageSpeed anahtarı varsa gerçek mobil puan; yoksa "yaklaşık ölçüm"), title/meta description/H1/başlık yapısı, yerel SEO (şehir/ilçe + ana hizmet ifadesi),
schema, noindex, sitemap, tıklanabilir telefon, WhatsApp, harita, form/randevu, hizmet/hakkımızda/referans/blog sayfaları, görseller ve alt metinleri, kırık iç bağlantılar,
sosyal medya bağlantıları, güncellik (telif yılı), e-ticaret işaretleri (ürün satan sektörlerde) ve **ele geçirilmiş/spam site** tespiti.

Dürüstlük kuralları: robots.txt taramaya izin vermiyorsa açılmaz · bot koruması (Cloudflare/403) "site bozuk" diye raporlanmaz, **"analiz edilemedi"** denir ·
JavaScript ile çizilen sitelerde (Wix/React) H1/içerik ölçülemez → "Doğrulanamadı" (yanlış "içerik az" bulgusu üretilmez) · özel ağ adreslerine istek atılmaz (SSRF koruması).

## Satış fırsatı nasıl belirlenir?

Her kontrol *sorun yok / sorun / doğrulanamadı* döner. Sorunlar önem × güvene göre puanlanır; sonuç anlamsız bir sayı olarak değil, **seviye + "Neden?" cümlesi** olarak gösterilir:

- **Yüksek** — güçlü, doğrulanmış bulgu(lar) veya birçok alanda somut eksik
- **Orta** — somut eksik var (kayıt kaynaklı çıkarımlar "Doğrulama gerekli" ile burada kalır)
- **Düşük** — somut eksik yok (güçlü dijital varlığı olan işletme sırf işletme olduğu için öne çıkarılmaz)
- **Belirsiz** — yeterli doğrulanmış veri yok (ör. site bot korumasıyla engellendi)

Blog/hakkımızda/sitemap gibi düşük önemli eksiklerin seviyeye katkısı sınırlıdır. Önerilen ilk hizmet, **toplam puana değil en güçlü tekil kanıta** göre seçilir.
Hizmetler yalnızca tespit edilen ihtiyaca bağlı önerilir. Kanıtı olmayan, sektör mantığına dayalı olası ihtiyaçlar (Google Ads, Tabela, Matbaa) ayrı bir
"Doğrulama gerektirir" bölümünde, seviyeyi etkilemeden gösterilir. Her işletme için: neden aramalı, satış görüşmesinde nereden başlanmalı, kısa satış notu üretilir.

## Satış paneli özellikleri

- **Satış fırsatı puanı (0–100):** `services/rule_engine/scoring.py`. Yalnızca gerçek tespitlerden hesaplanır (önem × güven; alan başına üst sınır); "Doğrulanamadı" alanlar puan vermez. Sektörel *varsayımlar* (Google Ads, tabela…) en fazla +8 katkı verir ve tabloda ayrıca "DOĞRULANMADI" etiketiyle görünür. Detayda **"Neden bu puanı aldı?"** tablosu satır satır puanı açıklar.
- **Mchttasarım Satış Fırsatları:** `services/rule_engine/opportunities.py`. Hizmet başına seviye, tespit edilen sorun + kanıt, neden öneriliyor, satış gerekçesi, sunulabilecek hizmet. *Tespite dayalı* ve *sektöre dayalı olası (doğrulanmadı)* fırsatlar ayrı gruplanır; kanıtı olmayan sorun uydurulmaz.
- **💡 Nasıl Çözülür? / 📚 Çözüm Rehberi:** `services/knowledge/guides.py` — 57 rehber (Web, Google İşletme Profili, Sosyal Medya, Reklam, Matbaa/Promosyon), her biri A–H bölümlü. Her kontrol bir rehbere bağlıdır; rehber işletmenin gerçek kanıtıyla birlikte açılır. `/rehber` sayfası sektöre göre uyarlanabilir kütüphanedir.
- **✍️ Satış Notu:** `services/knowledge/sales_note.py` — yalnızca analiz verisinden; doğrulanamayanlar "görüşmeden önce kontrol edin" olarak belirtilir.
- **CRM:** 9 kalıcı aşama (`packages/crm.py`: Yeni · Aranacak · Daha Sonra Ara · Arandı · Görüşüldü · Teklif Gönderildi · Takip Bekliyor · Kazanıldı · Kaybedildi), personel notu ve geçmiş (`PATCH /api/businesses/{id}/crm`). Doğrulama SIKIDIR: eski adlar (Teklif Verildi, Takipte, Müşteri Oldu, Olumsuz …) API'de reddedilir. Arama/iletişim SONUCU (ulaşılamadı, görüşüldü, ilgileniyor…) aşama değildir; iletişim geçmişinde tutulur (`POST /api/crm/{id}/contact`). **🎯 Bugünün potansiyel müşterileri:** analizi bitmiş, aranabilir aşamadaki (Yeni · Aranacak · Daha Sonra Ara · Takip Bekliyor) işletmeler; rakip/kamu/kendisi listelenmez.
- **"Daha önce analiz edildi"** rozeti ve "Daha önce analiz edilenleri gizle" filtresi. Aynı işletme ad + telefon + konum (≤60 m) ile eşleştirilir; şubeler birleştirilmez (`services/research/dedupe.py`).
- **📋 CRM (ayrı menü, `/crm`):** CRM'e aldığınız tüm firmalar tek ekranda; durum filtreleri (9 aşama + sayaçlar), sayfalama, arama (firma/telefon/adres/not), il · ilçe · sektör · önerilen hizmet filtreleri ve sıralama (son işlem, durum — önce *Aranacak*, skor, analiz tarihi). Her satırda skor, önerilen hizmet, kısa satış notu, CRM notu, analiz ve son işlem tarih/saati; Ara · WhatsApp · Google Maps · Web sitesi (yalnızca doğrulanmışsa) · Detay. Ana sayfada **CRM ÖZETİ** kartı.
- **CRM ≠ analiz:** analiz veya keşif firmayı CRM'e **eklemez**. CRM'de olmak `businesses.crm_added_at` doluluğudur; kartlardaki/detaydaki **➕ CRM'e Ekle** (durum + not) ile eklenir. Yeniden analiz CRM kaydını, notu ve geçmişi silmez. Firma detayında **CRM BİLGİLERİ** (durum tek tıkla değişir, CRM notu ✏️, son işlem) ve **🕘 CRM İşlem Geçmişi** (tarih/saat · durum · not; yalnızca eklenir, silinmez — `crm_activities`). Mantık: `services/crm_service.py`.
- **Analiz zaman damgası:** firma "🟢 Daha önce analiz edildi 18.09.2026 14:32" (Europe/Istanbul) gösterir; analiz tamamlanmadıysa "⚪ Henüz analiz edilmedi" (keşif/arama analiz sayılmaz). Firmanın son analiz tarihi ile analiz geçmişindeki kayıt (`analysis_jobs.completed_at`) aynı andır.
- **📊 Analiz raporu:** ana sayfada Bugün / Bu Hafta / Bu Ay / Toplam **tamamlanan analiz işlemi** sayısı (`analysis_jobs` — `completed`/`partial`; `failed` sayılmaz), Europe/Istanbul'a göre (bugün 00:00'dan, hafta Pazartesi 00:00'dan, ay 1'inden). Aynı firma bugün 2 kez analiz edildiyse 2 sayılır (rapor "2 analiz · 1 firma" der). Satıra tıklayınca o dönemde analiz edilen firmalar listelenir. Hesap: `services/reporting/analysis_stats.py`, uç noktalar: `GET /api/reports/analysis`, `GET /api/reports/analysis/businesses?period=today|week|month|all`.
- **Müşteri adayı uygunluğu:** "Bugünün potansiyel müşterileri" panelinde Mchttasarım'ın kendisi, **rakip firmalar** (web tasarım, reklam ajansı, matbaa, tabela…) ve **kamu kurumları/devlet okulları** listelenmez (`services/rule_engine/prospect.py`). Karar tek başına isme değil, Google kategorisi + sektör + ad birlikte değerlendirilerek verilir; belirsizse işletme aday kalır ("Özel …", "Koleji", "Okulları" gibi işaretli özel okullar elenmez). Ana listede elenen kayıtta gerekçeli "⛔ … müşteri adayı değil" etiketi görünür; puanı ve satış seviyesi değişmez.
- **Yenilemede durum koruma:** şehir/ilçe/sektör, filtreler, sıralama, arama işi ve sonuç listesi (+ scroll konumu) sekmeye özel `sessionStorage`'da tutulur (12 saat); F5'te geri gelir, yeni arama eskisini değiştirir. Depolama kullanılamazsa uygulama temiz başlar (`apps/web/app/_components/search-store.ts`).
- **Dışa aktarma:** sonuç listesi Excel (.xlsx) / CSV (UTF-8 BOM, `;` ayraçlı, formül enjeksiyonuna karşı korumalı), 17 sütun; bilinmeyen alanlar "Doğrulanamadı".
- **Hızlı aksiyonlar:** 📞 Ara (telefon yoksa gizli), 💬 WhatsApp (yalnızca 5xx mobil numaralarda), 📍 Google Maps, 🌐 Web Sitesi (yalnızca *doğrulanmış* adreste link; aksi halde tıklanamaz etiket), ✍️ Satış Notu, 💡 Nasıl Çözülür?, ➕ CRM'ye Ekle.

Mevcut analizleri yeni puan/fırsat alanlarıyla güncellemek için (yeni Google isteği atmadan, önbellekteki araştırmayla):

```bash
python -m services.worker.reanalyze --all          # veya --ids 1,2   (--new-research: araştırmayı da yenile)
```

## Satış operasyonu (huni, takip, satış planı, raporlar)

- **CRM aşamaları (9):** Yeni · Aranacak · Daha Sonra Ara · Arandı · Görüşüldü · Teklif Gönderildi · Takip Bekliyor · Kazanıldı · Kaybedildi. Eski adlar migration'larla (`e6f0a4b8c334`) veri kaybı olmadan dönüştürülür (Teklif Verildi→Teklif Gönderildi, Takipte→Takip Bekliyor, Müşteri Oldu→Kazanıldı, Olumsuz→Kaybedildi); API açılışında da DB'de kalmış eski adlar düzeltilir.
- **CRM kaydı:** sorumlu personel, sonraki takip tarihi/notu, son görüşme, ilgilenilen hizmet, teklif tutarı, satış tutarı, kaybedilme nedeni; her değişiklik `crm_activities` geçmişine (kullanıcı + zaman + meta) yazılır.
- **Takipler (`follow_ups` tablosu):** işletme + kullanıcı + tarih + saat + not + durum (Bekliyor/Tamamlandı/İptal); bir işletmede birden çok takip; Bugün / Gecikmiş / Yarın / Bu Hafta filtreleri (Europe/Istanbul takvim günü); tamamlama (sonuç + not + yeni tarih), düzenleme, iptal (silinmez). `businesses.next_follow_up_at` yalnızca en yakın bekleyen takibin önbelleğidir.
- **🔥 Bugün Kimi Aramalıyım?:** `services/sales/call_priority.py` — satış öncelik puanı (fırsat, aciliyet, hizmet uyumu, ticari yapı, dijital durum, rakipten kazanma, iletişim, CRM/takip) ve "Neden bugün aranmalı?" gerekçesi. Kapanmış, takibi ileri tarihli ve bugün görüşülmüş kayıtlar elenir; elenenler nedenleriyle sayılır.
- **💼 Satış planı (Ne satabilirim?):** hizmet bazında ihtiyaç / seviye / kanıt+kaynak (Google · Website · Social · Çapraz kontrol) / öncelik / yaklaşım; mevcut sağlayıcı sinyalleri (sayfa altı ajans kredisi, reklam etiketi, hazır platform — kanıt yoksa "Doğrulanamadı"); kaynaklar arası çelişkiler; kişiselleştirilmiş satış metinleri (yalnızca doğrulanmış bulgular olgu olarak geçer).
- **Hizmet ve Fiyat Ayarları (Yönetim):** fiyat aralıkları yalnızca yönetici girer; kodda fiyat yoktur. Fiyatsız hizmet "Fiyatlandırma yapılmadı" der; tahmini değer kesin teklif değildir.
- **Raporlar:** satış hunisi (kohort), hizmet/sektör bazlı "Para Nereden Geliyor?", personel performansı, dönemsel özet ve nesnel öneriler (örneklem < 5 ise "Yeterli veri bulunmuyor.").
- **E-posta (SMTP):** Yönetim → E-posta Ayarları (şifre şifreli saklanır, test başarılı olmadan aktifleştirilemez). Yeni kullanıcı daveti ve "Şifremi unuttum" tek kullanımlık, süreli bağlantı gönderir (düz şifre asla e-postalanmaz; DB'de yalnızca token özeti). `WEB_BASE_URL` bağlantı adresidir.

## Kurulum ve Çalıştırma — Docker Compose

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml exec api alembic upgrade head
docker compose -f infra/docker-compose.yml exec api python -m packages.db.seed
```

Panel: http://localhost:3000 · API sağlık kontrolü: http://localhost:8000/api/health

### Üretim (VPS, Nginx + HTTPS) — aynı köken mimarisi

Tarayıcı **tek bir kökenle** konuşur (örn. `https://pazar.mchttasarim.com.tr`); Nginx yolu ayırır: `/api/*` → API (`:8000`), diğer her şey → web (`:3000`).
Örnek yapılandırma: [`infra/nginx/nginx.conf.example`](infra/nginx/nginx.conf.example).

- **Web imajında API adresi gömülmez.** `NEXT_PUBLIC_*` değişkenleri `next build` sırasında pakete işlenir, çalışma anında (`environment:`) değiştirilemez. Bu yüzden varsayılan boştur ve tarayıcı `/api/...` göreli yoluna gider. Ayrı bir API alan adı gerekiyorsa `infra/docker-compose.yml` içindeki `web.build.args.NEXT_PUBLIC_API_BASE_URL` doldurulup imaj yeniden derlenir (`--build`).
- Nginx `/api`'yi yönlendirmezse istek Next.js'e ulaşır ve `next.config.mjs`'deki `/api` rewrite'ı API'ye aktarır (`API_INTERNAL_URL`, varsayılan `http://api:8000`). Tercih edilen yol yine Nginx'tir.
- Oturum çerezi `mch_session`: `HttpOnly`, `Path=/`, `SameSite=Lax`, host-only (Domain yok); `ENV=production` iken otomatik `Secure`. `.env` içinde `ENV=production`, `WEB_BASE_URL=https://pazar.mchttasarim.com.tr` ve `API_CORS_ORIGINS=https://pazar.mchttasarim.com.tr` olmalıdır. Ayarlar: `COOKIE_SECURE`, `COOKIE_SAMESITE`, `COOKIE_DOMAIN`.
- Oturum denetimi (`/api/auth/me`) 10 sn zaman aşımına sahiptir: giriş yoksa login ekranı, sunucuya ulaşılamazsa "Tekrar dene" düğmeli hata kartı gösterilir; arayüz sonsuz "Oturum kontrol ediliyor…" durumunda kalmaz.
- Web imajı değiştiğinde: `docker compose -f infra/docker-compose.yml build --no-cache web && docker compose -f infra/docker-compose.yml up -d web`.

## Yerel Geliştirme (Docker olmadan)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # Google/Bing Haritalar araştırması için gerçek tarayıcı
# Postgres ve Redis çalışıyor olmalı (brew services start postgresql@16 redis); .env içindeki DATABASE_URL'yi kendi kullanıcınıza göre düzenleyin
set -a && source .env && set +a

alembic upgrade head
python -m packages.db.seed

uvicorn apps.api.main:app --reload --port 8000                                   # terminal 1
celery -A services.worker.celery_app worker --loglevel=info -P threads -c 4     # terminal 2 (web sitesi analizleri paralel yapılır)
cd apps/web && npm install && npm run dev                                        # terminal 3 — http://localhost:3000
```

> Worker'ı kod değişikliğinden sonra yeniden başlatmak gerekir (uvicorn `--reload` yalnızca API'yi yeniler).

## Environment Variables (`.env`)

| Değişken | Açıklama | Zorunlu mu? |
|---|---|---|
| `DATABASE_URL`, `REDIS_URL` | Postgres / Celery broker | Evet |
| `DISCOVERY_PROVIDER` | `google_maps` (varsayılan, anahtarsız) / `google` (Places API) / `mock` (sadece test). Eski `osm` değeri otomatik `google_maps` olur | Hayır |
| `RESEARCH_ENABLED` | Çok kaynaklı araştırma (varsayılan `true`; testlerde kapalı) | Hayır |
| `GOOGLE_PLACES_API_KEY` | Yalnızca resmi API modunda (`DISCOVERY_PROVIDER=google`) | Google modunda |
| `GOOGLE_PLACES_FETCH_REVIEWS` | Son yorum tarihi için yorum alanını da iste (daha pahalı SKU), varsayılan `true` | Hayır |
| `GOOGLE_PAGESPEED_API_KEY` | Gerçek mobil sayfa hızı puanı (anahtarsız kota sıfırdır) | Hayır |
| `AI_PROVIDER`, `ANTHROPIC_API_KEY` | Opsiyonel AI yorumlama (varsayılan `none`; sistem AI olmadan tam çalışır) | Hayır |
| `API_SECRET_KEY`, `API_CORS_ORIGINS`, `WEB_BASE_URL` | Backend gizli anahtarı / CORS / e-posta bağlantı adresi (üretimde `https://alan-adi`) | Evet (varsayılanlar dev için yeterli) |
| `COOKIE_SECURE`, `COOKIE_SAMESITE`, `COOKIE_DOMAIN` | Oturum çerezi (varsayılan: `ENV=production` iken Secure, Lax, host-only) | Hayır |
| `NEXT_PUBLIC_API_BASE_URL` | Yalnızca `next dev` için (varsayılan `http://localhost:8000`). Build-time'dır; üretimde boş bırakılır (aynı köken `/api`) | Hayır |

**Güvenlik:** `.env` Git'e eklenmez; API anahtarları yalnızca backend'de okunur.

## Resmi Google Places API modu (opsiyonel)

1. Google Cloud'da faturalandırması açık bir proje için Places API (New) anahtarı oluşturun.
2. `.env`: `DISCOVERY_PROVIDER=google` ve `GOOGLE_PLACES_API_KEY=<anahtar>`.
3. Servisleri yeniden başlatın. Google profili analizi (puan, yorum sayısı, fotoğraf, kategori uyumu, rakiplere göre yorum sayısı, son yorum tarihi) otomatik devreye girer.

## Testler

```bash
createdb mchttasarim_test   # bir kereye mahsus
pytest tests/ -v
```

Gerçek ağ çağrısı yapılmaz (Google/Bing yanıtları ve web siteleri mock'lanır; testlerde `RESEARCH_ENABLED=false`); Celery worker gerekmez.

## Oturum: "Beni hatırla"

Giriş ekranındaki kutu işaretliyse oturum çerezi kalıcıdır (30 gün, kullanıldıkça uzar, en fazla 90 gün; HttpOnly, SameSite=Lax, sunucuda yalnızca token özeti). İşaretsizse çerez tarayıcı kapanınca silinir (sunucu tarafı süre 7 gün kayan, en fazla 30 gün). Çıkış oturumu sunucudan siler; pasifleştirilen kullanıcının oturumları geçersiz olur. Reddedilen oturumların nedeni (`bilinmeyen token / süresi doldu / mutlak sınır / pasif kullanıcı`) API günlüğüne yazılır.

## Kullanıcı bazlı analiz geçmişi

"Daha önce analiz edildi" yalnızca **bakan kullanıcının** o işletme için kendi başarılı (`completed`) analizi varsa görünür (`user_analyses`: unique user + business + type). Başka kullanıcının analizi ya da işletmenin sistemde bulunması bunu doğurmaz; o kullanıcı işletmeyi yeniden analiz edebilir. Her analiz işlemi yine `analysis_jobs`'ta ayrı satırdır. Kullanıcısı bilinmeyen eski analizler hiçbir kullanıcıya atfedilmez.
