# Mchttasarım Marketing OS — Tasarım Dokümanı

Tarih: 2026-09-18
Durum: Onay bekliyor (kodlama başlamadı)

## Amaç

Mchttasarım Reklam Ajansı için, potansiyel müşteri keşfinden aylık performans raporlamasına kadar tüm pazarlama operasyonunu tek sistemde yöneten, bölge/sektör bazlı otomatik işletme keşfi yapan ve her işletme için "Mchttasarım bu işletmeye ne satabilir?" sorusuna kanıta dayalı cevap üreten bir iç operasyon platformu.

Kullanıcı kitlesi: sadece Mchttasarım ekibi (müşteri portalı yok).

---

## 1. Final Teknoloji Mimarisi

| Katman | Teknoloji | Neden |
|---|---|---|
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind + TanStack Query | Panel/dashboard için hızlı geliştirme, tip güvenliği |
| Backend API | Python + FastAPI (async) | İş mantığı, iş kuyruğuna job atma, CRUD |
| Arka plan işleri | Celery + Redis (broker + result backend) | Scraping/AI/rapor gibi uzun işler senkron isteği bloklamasın |
| Zamanlanmış görevler | Celery Beat | Aylık rapor tetikleme (Faz 3) |
| Veritabanı | PostgreSQL 15+ | İlişkisel veri + JSONB (kanıt/finding payload'ları için) |
| Cache / Rate-limit / Job durumu | Redis | Entegrasyon bazlı yapılandırılabilir cache, token-bucket rate limit, job progress pub/sub |
| AI | Claude API (Anthropic), sağlayıcıdan soyutlanmış `ai_orchestration` katmanı | Analiz yorumlama, önceliklendirme, metin üretimi |
| PDF üretimi | WeasyPrint (HTML→PDF) | Teklif belgesi çıktısı |
| Reverse proxy | Nginx + Certbot | SSL, VPS üzerinde servis yönlendirme |
| Konteyner | Docker Compose | web, api, worker, beat, postgres, redis, nginx servisleri; VPS'e taşınabilir |
| Hata takibi | Sentry (self-hosted veya cloud, opsiyonel) + yapılandırılmış JSON log | Job/pipeline hatalarını izlemek |
| Secrets | `.env` (repoya girmez) + `pydantic-settings`, entegrasyon başına ayrı config bloğu | API anahtarları asla frontend'e gitmez |

Not: Home dizininiz (`/Users/mucahit`) bütünüyle bir git deposu olarak yapılandırılmış görünüyor — bu proje için ayrı, temiz bir depo (`mchttasarim-marketing-os/`) açtım. İsterseniz ana git kurulumunuzu ayrıca gözden geçirebiliriz, ama bu doküman kapsamında ona dokunmadım.

---

## 2. Monorepo Klasör Yapısı

```
mchttasarim-marketing-os/
├── apps/
│   ├── web/                          # Next.js frontend (panel)
│   └── api/                          # FastAPI backend (HTTP katmanı, sadece orkestrasyon)
├── services/
│   ├── worker/                       # Celery worker entrypoint
│   │   └── tasks/
│   │       ├── discovery.py
│   │       ├── analysis.py
│   │       ├── proposal.py
│   │       └── reporting.py          # Faz 3
│   ├── ai_orchestration/             # Claude pipeline'ları, sağlayıcıdan bağımsız arayüz
│   │   ├── pipelines/
│   │   │   ├── evidence_interpretation.py
│   │   │   ├── opportunity_matching.py
│   │   │   ├── sales_strategy.py
│   │   │   └── proposal_generation.py
│   │   └── provider/anthropic_client.py
│   ├── rule_engine/                  # Service Catalog kuralları — deterministic matching
│   │   └── scoring.py
│   └── integrations/                 # Her dış servis kendi klasöründe, izole
│       ├── google_places/
│       │   ├── client.py
│       │   └── policy.py             # kota / rate-limit / cache / ToS / attribution config
│       ├── google_pagespeed/
│       ├── website_crawler/
│       ├── social_discovery/         # sadece link tespiti (Faz 1), Faz 2'de genişler
│       ├── google_business_profile/  # Faz 4, OAuth
│       ├── google_ads/               # Faz 4
│       └── meta_ads/                 # Faz 4
├── packages/
│   ├── db/                           # SQLAlchemy modelleri + Alembic migration'ları
│   └── shared_types/                 # Pydantic şemaları (frontend tipleri buradan türetilir)
├── docs/
│   └── plans/                        # Bu doküman gibi tasarım kayıtları
├── infra/
│   ├── docker-compose.yml
│   └── nginx/
└── .env.example
```

**Önemli prensip:** Her `integrations/<servis>/policy.py`, o servisin güncel kullanım şartlarına göre şu alanları taşır: `terms_url`, `quota`, `rate_limit`, `cache_ttl_by_field`, `attribution_requirement`, `requires_oauth`, `last_reviewed_at`. Sabit "30 gün cache" gibi varsayımlar kod içine gömülmez; bu dosyalardan okunur ve `integrations_registry` tablosunda da yansıtılır, böylece kurallar değiştiğinde tek yerden güncellenir.

---

## 3. PostgreSQL Tabloları ve İlişkiler

```
regions            (id, name, parent_region_id→regions.id, level[il|ilçe], center_lat, center_lng, search_radius_m)
sectors            (id, name, google_place_types[], keyword_variants[])

businesses         (id, name, sector_id→sectors, region_id→regions,
                    address, lat, lng, phone, website,
                    google_place_id UNIQUE,           -- Discovery Data
                    google_rating, google_review_count, photo_count,
                    discovery_source, status[discovered|analyzing|analyzed],
                    crm_stage, opportunity_score_total, sales_priority,
                    created_at, updated_at, last_analysis_at)

authorized_profiles (id, business_id→businesses UNIQUE,   -- Authorized Business Profile Data (Faz 4)
                    oauth_account_id, granted_scopes[], connected_at,
                    profile_insights JSONB)             -- discovery verisinden AYRI tablo

discovery_jobs     (id, region_id, sector_id, target_count, status,
                    found_new, found_existing, error_message,
                    requested_by, created_at, completed_at)
discovery_job_results (job_id→discovery_jobs, business_id→businesses)

analysis_jobs      (id, business_id→businesses, status,
                    stages_status JSONB,   -- {"places":"success","website":"success","instagram":"failed","seo":"pending"}
                    started_at, completed_at)

findings           (id, business_id→businesses, analysis_job_id→analysis_jobs,
                    category[website|gbp|social|seo|ads|visual|print],
                    severity[none|low|medium|high],
                    evidence TEXT, source[places|website_crawl|pagespeed|social|ai_interpretation|manual],
                    confidence[low|medium|high],
                    detected_at, raw_data JSONB)

opportunity_scores (id, business_id, analysis_job_id,
                    dimension[web|seo|google_visibility|social|ads|design|print],
                    score INT 0-100, reasoning TEXT, based_on_finding_ids INT[])

services_catalog   (id, service_name, description, target_sectors[],
                    required_signals JSONB, opportunity_rules JSONB,
                    sales_arguments TEXT[], deliverables TEXT[], default_priority)

service_recommendations (id, business_id, analysis_job_id, service_id→services_catalog,
                    matched_rule TEXT, priority_rank INT, ai_justification TEXT)

proposals          (id, business_id, status, problems_summary, opportunities_summary,
                    recommended_services JSONB, scope_of_work TEXT, marketing_goals TEXT,
                    work_plan TEXT, price_items JSONB, valid_until, pdf_url, created_at)

crm_activities     (id, business_id, type[status_change|note|call|meeting],
                    from_stage, to_stage, note TEXT, created_by, created_at)

api_usage_ledger   (id, integration_name, endpoint, called_at, cost_units,
                    quota_period, business_id NULLABLE)

integrations_registry (id, name, terms_url, quota_config JSONB, cache_policy JSONB,
                    requires_oauth BOOL, attribution_requirements TEXT, last_reviewed_at)

campaign_drafts    (id, business_id, channel[google_ads|meta_ads], draft_json, created_at)   -- Faz 3
content_plans      (id, business_id, plan_json, month, created_at)                            -- Faz 3
monthly_reports    (id, business_id, month, metrics JSONB, generated_summary TEXT, created_at) -- Faz 3

users              (id, email, name, role, created_at)
```

**Kritik ayrım (madde 1):** `businesses` tablosundaki alanlar tamamen **Discovery Data** (Google Places'ten kamuya açık, izinli alanlar). `authorized_profiles` tablosu ayrı ve boş başlar — yalnızca işletme sahibi OAuth ile bağlandığında (Faz 4) doldurulur. Kod seviyesinde de bu iki veri kaynağı ayrı serializer/response modellerinde temsil edilir, hiçbir zaman karıştırılmaz.

---

## 4. API Endpoint Listesi

```
GET    /api/regions                          # il/ilçe ağacı
GET    /api/sectors

POST   /api/discovery/jobs                   # {region_id, sector_id, target_count}
GET    /api/discovery/jobs/{id}               # canlı ilerleme

GET    /api/businesses                        # filtre: region, sector, opportunity aralığı, crm_stage
GET    /api/businesses/{id}                   # findings + scores + recommendations dahil
POST   /api/businesses/{id}/analyze           # tekil analiz başlat
POST   /api/businesses/analyze-bulk           # {business_ids[]} veya {top_n:10, filter}
GET    /api/analysis-jobs/{id}                # stage bazlı durum

GET    /api/businesses/{id}/findings
GET    /api/businesses/{id}/opportunity-scores
GET    /api/businesses/{id}/service-recommendations

POST   /api/businesses/{id}/proposals         # son analizden teklif taslağı üret
PATCH  /api/proposals/{id}                    # fiyat/metin düzenleme
POST   /api/proposals/{id}/pdf
GET    /api/proposals/{id}

PATCH  /api/businesses/{id}/crm-stage         # + otomatik activity log
POST   /api/businesses/{id}/activities        # not/görüşme/arama
GET    /api/businesses/{id}/activities

GET    /api/dashboard/stats                   # bugünkü keşifler, analiz bekleyen, yüksek fırsatlı, teklif bekleyen, kazanılan

GET/POST/PATCH /api/service-catalog           # hizmet kataloğu yönetimi

# Faz 3
POST   /api/businesses/{id}/campaign-drafts/google-ads
POST   /api/businesses/{id}/campaign-drafts/meta-ads
POST   /api/businesses/{id}/content-plan
POST   /api/businesses/{id}/monthly-report

# Faz 4
GET    /api/oauth/google-business/connect
GET    /api/oauth/google-business/callback
```

---

## 5. AI Orchestration Yapısı

AI tek bir "bu işletmeyi analiz et" çağrısı değil, her aşaması ayrı kayıt altına alınan bir pipeline'dır:

```
1. Data Collection        → integrations/* katmanından ham veri (places, website, social, seo)
2. Data Normalization     → kaynak bazlı ham veriyi ortak şemaya indirger
3. Evidence Extraction    → DETERMİNİSTİK kod, Finding üretir (category/severity/evidence/source/confidence/detected_at)
                             AI KULLANILMAZ — "web sitesi alanı boş" → finding(website, missing, source=places, confidence=high)
4. Rule Engine            → Finding seti, services_catalog.required_signals ile eşleştirilir → aday ServiceRecommendation listesi (AI'siz, gerekçesi matched_rule)
5. AI Analysis            → Claude'a SADECE yapılandırılmış Finding + aday eşleşme listesi verilir (ham HTML/JSON değil);
                             prompt açıkça: "Finding listesinde olmayan hiçbir bilgi üretme, her yorumda finding_id referans ver" talimatını içerir
6. Opportunity Matching   → AI, rule engine'in ürettiği ADAY listesini önceliklendirir/yorumlar; kod seviyesinde AI çıktısı,
                             rule engine'in çıkardığı hizmet setiyle doğrulanır — AI listede olmayan yeni bir hizmet EKLEYEMEZ
7. Sales Strategy         → her zincir için Problem → Kanıt → Fırsat → Önerilen Hizmet → Pazarlama Amacı → Satış Yaklaşımı yapısında metin
8. Proposal Generation    → 3-7 çıktılarından teklif taslağı; fiyat alanları AI tarafından doldurulmaz, boş bırakılır
```

Her aşamanın girdi/çıktısı `analysis_jobs` ve `findings`/`service_recommendations` tablolarında saklanır → tamamen izlenebilir ve hata ayıklanabilir. AI aşaması (5-8) başarısız olursa, 1-4 aşamalarının deterministik sonuçları (findings, aday hizmetler) yine de panelde gösterilir — sistem "AI yoksa hiçbir şey yok" durumuna düşmez.

**Kanıt zorunluluğu (madde 12'nin karşılığı):** Her `Finding` şu yapıyı taşır ve panelde bu haliyle gösterilir:

```
finding:
  category: website
  severity: high
  evidence: "İşletme için Google Places kaydında web sitesi alanı boş."
  source: places
  confidence: high
  detected_at: 2026-09-18T09:12:00Z
```

AI yorumu gerektiren bulgular (ör. "sosyal medya içerik kalitesi düşük") `source: ai_interpretation` ve genelde `confidence: medium/low` ile işaretlenir — asla `places`/`website_crawl` gibi doğrulanmış kaynaklarla aynı güven seviyesinde sunulmaz. Doğrulanamayan hiçbir bilgi "kesin" gibi yazılmaz; belirsizse finding `confidence: low` + evidence içinde "doğrulama gerekiyor" notuyla işaretlenir.

---

## 6. Discovery Pipeline (Bölge → İşletme Listesi)

1. Frontend `POST /api/discovery/jobs` → `DiscoveryJob(status=queued)` oluşturulur, Celery kuyruğuna atılır, `job_id` hemen döner.
2. Worker, `region_id`'yi `regions` tablosundan lat/lng + yarıçapa, `sector_id`'yi Google Places kategori kodu + Türkçe anahtar kelime varyasyonlarına çözer.
3. `integrations/google_places/policy.py`'de tanımlı kota/rate-limit'e göre Nearby/Text Search çağrılır; her çağrı `api_usage_ledger`'a işlenir.
4. Yeni işletme adaylarında Place Details çağrısı yapılır (telefon, web sitesi, adres, puan, yorum sayısı, kategori, konum — **sadece izinli Discovery Data alanları**); sonuç `policy.py`'deki `cache_ttl_by_field`'a göre Redis'te önbelleklenir.
5. `google_place_id` ile tekilleştirme yapılır; yeni işletme `status=discovered` ile `businesses`'a yazılır, mevcutsa güncellenir.
6. Hedef sayıya ulaşılınca veya kaynak/kota tükenince `DiscoveryJob.status=completed`, `found_new`/`found_existing` raporlanır. Panel bu aşamada sadece Discovery Data gösterir — derin analiz henüz tetiklenmemiştir.

"Türkiye geneli" gibi geniş taramalar Faz 1'de desteklenmez (Places Nearby Search'ün ~50km yarıçap sınırı nedeniyle ülke geneli tarama grid-tabanlı bölme gerektirir); MVP tanımlı il/ilçe listesiyle sınırlıdır, ülke geneli Faz 2+'da ayrı bir "grid tarama" tasarımıyla ele alınır.

---

## 7. Analysis Pipeline (İşletme Detayında "Analiz Et")

Celery **group** (paralel, birbirinden bağımsız alt görevler) olarak çalışır — biri başarısız olsa diğerleri etkilenmez:

```
group([
  task_google_profile_enrich(business_id),
  task_website_analyze(business_id),      # website varsa: robots.txt kontrolü, başlık/meta, https, PageSpeed
  task_social_discover(business_id),      # sadece link tespiti + herkese açık meta veri (Faz 1)
  # Faz 2: task_seo_analyze, task_competitor_analyze, task_social_deep_analyze
])
→ chord callback: evidence_extraction(business_id, analysis_job_id)
→ rule_engine.match(business_id)
→ ai_pipeline.run(business_id)   # madde 5'teki 5-8. aşamalar
```

`analysis_jobs.stages_status` her alt görevin sonucunu ayrı ayrı tutar (`{"places":"success","website":"success","instagram":"failed","seo":"pending"}`), panel bunu olduğu gibi gösterir (madde 12: kısmi sonuç şeffaflığı). Başarısız/bekleyen aşamalar için de bir "finding" üretilir (ör. `category: social, severity: none, evidence: "Instagram verisi toplanamadı", source: manual, confidence: low`) — sessizce atlanmaz.

---

## 8. Opportunity / Service Matching Sistemi

**Service Catalog örneği:**

```
service: Web Tasarım
required_signals: [website.status == missing OR website.status == broken OR website.mobile_friendly == false]
opportunity_rules: { missing: 100, broken: 90, poor_mobile: 60 }
sales_arguments: ["Web sitesi olmayan işletmeler aramalarda görünmez", ...]

service: Google Ads
required_signals: [sector.commercial_intent == high, seo.organic_visibility == low, competitor.ads_active == true]
opportunity_rules: { all_signals_present: 85, partial: 50 }

service: Sosyal Medya Yönetimi
required_signals: [social.posting_regularity == low, social.profile_completeness == low]
```

**Boyut skorları** (`opportunity_scores.dimension`): web, seo, google_visibility, social, ads, design, print — her biri rule engine tarafından finding'lerden hesaplanan 0-100 arası **kural tabanlı** bir sayıdır (AI'nin uydurduğu tek bir gizemli sayı değil). AI yalnızca bu skorların yorumunu/önceliklendirmesini yapar, ham sayıyı rule engine'in belirlediği aralık dışına çıkaramaz (kod seviyesinde clamp edilir).

**Genel Mchttasarım Fırsat Skoru** = boyut skorlarının ağırlıklı toplamı (ağırlıklar `services_catalog`/`ScoringConfig` üzerinden yapılandırılabilir).

**Satış önceliği** (Yüksek/Orta/Düşük) = toplam skor eşiklerinden türetilir, ancak veri kapsamı da hesaba katılır: eğer bulguların çoğu `confidence: low` veya toplanamamışsa, öncelik en fazla "Orta" ile sınırlandırılır — ince/eksik veriyle "Yüksek fırsat" iddiası yapılmaz.

---

## 9. CRM Yapısı

Durumlar: `Yeni → Analiz bekliyor → Analiz edildi → İletişime geçilecek → İletişime geçildi → Görüşme yapıldı → Teklif hazırlanıyor → Teklif gönderildi → Takipte → Kazanıldı / Kaybedildi`

- Çoğu geçiş doğrusal ileri yönlüdür, ama geri alma ve atlama serbesttir; `Kaybedildi` her aşamadan erişilebilir.
- Her durum değişikliği (otomatik veya manuel), not, arama ve görüşme kaydı `crm_activities` tablosuna `type` alanıyla ayrılarak yazılır — tam denetim izi.
- Teklif oluşturma (`POST /proposals`) otomatik olarak `crm_stage`'i "Teklif hazırlanıyor"a taşır ve activity log'a yazar.

---

## 10. MVP Sprint Planı

| Sprint | Kapsam |
|---|---|
| 0 | Repo, docker-compose, DB migration altyapısı, `.env` iskeleti, `integrations_registry` seed |
| 1 | Region/Sector taxonomy + Discovery pipeline (Google Places) + işletme listesi ekranı |
| 2 | İşletme detay sayfası + temel veri gösterimi + Analysis pipeline iskeleti (henüz AI yok — sadece Places+website stage + deterministic Finding üretimi) |
| 3 | Service Catalog + Rule Engine + Opportunity Scoring (boyut skorları, gerekçeler, satış önceliği) — tamamen deterministik |
| 4 | AI Orchestration entegrasyonu (Claude ile yorumlama, önceliklendirme, satış yaklaşımı metni) |
| 5 | Teklif sistemi (proposal generation + PDF) + CRM stage yönetimi + activity log |
| 6 | Dashboard istatistikleri, toplu analiz ("seçilenleri analiz et" / "top-10"), hata/partial-result UI, genel polish |

Sprint 6 sonunda madde 14'teki tam MVP akışı ("Bölge seç → ... → CRM'e kaydet") uçtan uca çalışır durumda olur. Faz 2/3/4 aynı sprint mantığıyla, kullanıcının belirttiği sırayla devam eder.

---

## 11. Geliştirme Sırası (bağımlılık sırasına göre)

1. DB şeması + Alembic migrations
2. `integrations_registry` + Google Places client (policy dosyasıyla)
3. Discovery job + Celery altyapısı
4. Business list UI
5. Website crawler (robots.txt'e saygılı, kendi basit httpx/BeautifulSoup kodu)
6. Evidence extraction (deterministik)
7. Service Catalog seed verisi + Rule Engine
8. Opportunity scoring hesaplama
9. Business detail UI (findings/scores/recommendations)
10. AI Orchestration (Claude entegrasyonu, prompt şablonları, madde 5'teki doğrulama kısıtları)
11. Proposal generation + PDF
12. CRM stage + activity log
13. Dashboard/istatistikler
14. Faz 2+ entegrasyonları (rakip analizi, SEO, sosyal medya derinlemesine, Google/Meta Ads taslakları, aylık rapor, OAuth)

---

## 12. Kullanılacak Harici API'ler ve Nedenleri

| Servis | Faz | Neden / Not |
|---|---|---|
| Google Places API (New) | 1 | Resmi API, işletme keşfi için birincil kaynak. UI'da Google attribution gereksinimi karşılanmalı. |
| Google PageSpeed Insights API | 1 | Ücretsiz, resmi; web sitesi performans/mobil uyumluluk sinyali. |
| Website crawling (kendi kod) | 1 | Resmi API yoktur; sadece robots.txt'e izinli genel sayfalar taranır — arama motorlarının yaptığına benzer standart, kamuya açık bir uygulama. |
| Sosyal medya link tespiti | 1 | Sadece Google/website üzerinden link tespiti; yetkisiz hesap için aktif scraping YAPILMAZ (ToS gereği). |
| Instagram/Facebook Graph API | 2 (bağlıysa) / 4 (tam) | Sadece işletme sahibinin yetkilendirdiği hesaplarda kullanılır; yetkisiz hesaplarda veri "doğrulanmadı" olarak işaretlenir. |
| SEO veri sağlayıcı (ör. DataForSEO) | 2 | Ücretli, resmi API; rakip organik görünürlük karşılaştırması için. |
| Google Business Profile API | 4 | Sadece OAuth ile işletme sahibi bağlarsa — Authorized Business Profile Data. |
| Google Ads API / Meta Marketing API | 4 | Gerçek kampanya push'u sadece bu fazda; MVP'de sadece taslak metin (API'siz). |
| Claude API (Anthropic) | 1 | Analiz yorumlama, önceliklendirme, satış/teklif metni üretimi — ham veri değil, sadece yapılandırılmış Finding'ler gönderilir. |

Her entegrasyonun ToS/kota/cache/attribution detayları kodda değil, `integrations/<servis>/policy.py` + `integrations_registry` tablosunda canlı tutulur; hiçbiri için sabit varsayım yapılmaz.

---

## 13. Aylık API/AI Maliyetini Belirleyen Faktörler

Şu an net bir $ rakamı vermek yanıltıcı olur — fiyatlandırmalar değişebiliyor ve gerçek kullanım paternine bağlı. Maliyeti belirleyen ana faktörler:

- **Discovery hacmi**: kaç bölge × kaç sektör × ortalama sonuç sayısı taranıyor (Places Nearby Search + Place Details çağrı sayısı). Place Details önbellekleme bu maliyeti düşürür.
- **Derin analiz oranı**: 50 işletme bulunsa da hepsi otomatik analiz edilmiyor — "seçilenleri analiz et" / "top-10" kısıtı (madde 8) sayesinde asıl maliyet sadece gerçekten analiz edilen işletme sayısına bağlı.
- **Claude API kullanımı**: analiz edilen işletme başına gönderilen Finding JSON boyutu (girdi token) + üretilen yorum/teklif metni uzunluğu (çıktı token).
- **SEO veri sağlayıcı** (Faz 2+): genelde aylık sabit paket + sorgu başı ücret.
- **VPS**: sabit aylık maliyet, worker sayısı arttıkça (paralel analiz kapasitesi) ölçeklenir.

Toplam maliyet kabaca: `(taranan işletme × derin analiz oranı × işletme başına ortalama API+AI maliyeti) + sabit altyapı maliyeti`. Öneri: MVP'de `integrations_registry` + `api_usage_ledger` üzerinden günlük/aylık kota koymak, birkaç hafta gerçek kullanımdan sonra somut maliyet ölçümü yapmak.

---

## Özet: MVP Çekirdek Akış (Faz 1)

```
Bölge seç → Sektör seç → İşletme bul (Discovery) → İşletme listesi
→ İşletme detayını aç → Analiz başlat (Places + Website + Social-link stage'leri)
→ Evidence Extraction (deterministik Finding'ler) → Rule Engine (aday hizmetler)
→ AI Analysis (yorumlama + önceliklendirme, sadece Finding'lere dayanarak)
→ Fırsat skorları + Satış önceliği → Teklif oluştur → PDF → CRM'e kaydet
```

Faz 2: rakip analizi, SEO analizi, sosyal medya derinlemesine analiz, PDF rapor geliştirme, gelişmiş teklif sistemi.
Faz 3: Google Ads / Meta Ads taslakları, içerik planlama, aylık raporlama.
Faz 4: OAuth, Google Business Profile bağlantısı, Google Ads API, Meta Marketing API, gelişmiş otomasyon.

