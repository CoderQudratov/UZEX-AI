# UZEX AI — Render Free Deployment & Reliability Guide

Ushbu hujjat UZEX AI tizimini **Render Free Web Service** platformasiga Docker orqali bepul, xavfsiz va xotiradan tejamkor ravishda deploy qilish hamda tashqi monitoring orqali sovuq yuklanishni (cold-start) minimallashtirish bo‘yicha to‘liq qo‘llanmadir.

---

## 1. Texnik Ko‘rsatkichlar va Resurs Sig‘imi

Render Free Tier quyidagi qat’iy limitlarga ega:
- **RAM**: 512 MB (maksimal).
- **CPU**: 0.1 vCPU (bo‘lingan).
- **Faol bo‘lmaganda to‘xtatish (Spin down)**: 15 daqiqa davomida so‘rov kelmasa, xizmat uyqu holatiga o‘tadi.
- **Oylik bepul limit**: 750 soat/oy.

### Haqiqiy O‘lchov Natijalari (Benchmarked on local runtime):
| Ko‘rsatkich | O‘lchangan qiymat | Render Free Cheklovi | Holat |
|---|---|---|---|
| **Baza hajmi (DuckDB)** | 28.51 MB (500k bitim) | Disk limitiga mos | **Optimal** |
| **Baza yozuvdan himoyasi** | Faqat Read-Only (`0444`) | Yozuvsiz | **Xavfsiz** |
| **Boshlang‘ich RAM (RSS)** | 150.57 MB | < 512 MB | **A’lo (~29%)** |
| **Maksimal yuklama RAM** | 160.24 MB | < 512 MB | **A’lo (~31%)** |
| **Sovuq start (Startup)** | 1.26 soniya | < 30 soniya | **Juda tez** |
| **`/health` kechikishi** | 1.24 ms | < 100 ms | **Stateless / Fast** |
| **`/` (Frontend) kechikishi**| 4.68 ms | < 100 ms | **Yengil** |
| **Bitta chat so‘rovi** | 28.05 ms | < 500 ms | **Tezkor** |
| **12 ta parallel so‘rov** | 53.77 ms | < 2000 ms | **Barqaror** |
| **Disk spilling / WAL** | 0 ta fayl (Nol) | Read-only | **Toza** |
| **Taxminiy Docker Image** | ~365 MB | < 1 GB | **Kompakt** |

---

## 2. GitHub Omboriga Joylash

Render avtomatik tarzda GitHub omboringiz bilan sinxronlashadi.

1. Git o‘zgarishlarini tekshiring:
   ```bash
   cd /home/doston/Desktop/UZEX
   git status
   ```
2. Loyihani GitHub-ga yuboring:
   ```bash
   git add uzex-ai/
   git commit -m "feat: complete Phase 6 and Phase 7 Render Free Docker readiness"
   git push origin main
   ```
> [!IMPORTANT]
> Hech qachon `.env` faylini yoki `GEMINI_API_KEY` kalitini GitHub-ga commit qilmang! `.gitignore` va `.dockerignore` ularni chiqarib tashlagan.

---

## 3. Render Dashboard Orqali Xizmatni Yaratish

### Variant A: `render.yaml` Blueprint orqali (Avtomatik)
1. [Render Dashboard](https://dashboard.render.com/) ga kiring.
2. **Blueprints** bo‘limiga o‘ting va omboringizni ulang.
3. Repozitoriyadagi `uzex-ai/render.yaml` fayli avtomatik aniqlanadi.
4. Render so‘ragan `GEMINI_API_KEY` qiymatini kiriting va **Apply** tugmasini bosing.

---

### Variant B: Manual Web Service yaratish (Qo‘lda)
1. **New +** → **Web Service** ni tanlang.
2. GitHub omboringizni tanlang (`UZEX` yoki `uzex-ai`).
3. Quyidagi parametrlarni o‘rnating:
   - **Name**: `uzex-ai`
   - **Region**: `Frankfurt (EU Central)` yoki o‘zingizga eng yaqin mintaqa.
   - **Branch**: `main`
   - **Root Directory**: `uzex-ai`
   - **Runtime**: `Docker`
   - **Instance Type**: `Free`
4. **Health Check Path**: `/health` (juda muhim: bu Render-ga xizmat to‘liq ko‘tarilganini bildiradi).

---

## 4. Muhit O‘zgaruvchilarini (Environment Variables) Sozlash

Render Dashboard-dagi **Environment** bo‘limida quyidagi o‘zgaruvchilarni kiriting:

| O‘zgaruvchi | Qiymat | Tavsif |
|---|---|---|
| `APP_ENV` | `production` | Production rejimi (qat’iy talablar) |
| `DATABASE_PATH` | `data/processed/uzex.duckdb` | Imagedagi read-only baza yo‘li |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Tasdiqlangan Gemini Flash modeli |
| `GEMINI_API_KEY` | `AIzaSy...` (maxfiy) | Google AI Studio kalitingiz |
| `MAX_CONCURRENT_QUERIES` | `4` | RAM limitidan chiqmaslik uchun |
| `GEMINI_TIMEOUT_SECONDS` | `20` | Gemini so‘rov vaqti chegarasi |

> [!NOTE]
> `PORT` o‘zgaruvchisi Render tomonidan avtomatik beriladi (odatda 10000). Bizning `Dockerfile` buyrug‘imiz (`exec /srv/uzex/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log`) buni avtomatik tarzda dinamik qabul qiladi.

---

## 5. Xizmatni Ishga Tushirish va Tekshirish (Public URL Verification)

Render deploy jarayonini tugatgach, xizmatga ommaviy URL beradi:  
`https://uzex-ai.onrender.com` (yoki siz tanlagan nom).

Quyidagi buyruqlar orqali xizmatni tekshiring:
```bash
# 1. Tezkor liveness tekshiruvi (DuckDB va Gemini chaqirilmaydi)
curl -i https://YOUR-SERVICE.onrender.com/health

# 2. Xizmat statusi va ombor versiyasini tekshirish
curl -s https://YOUR-SERVICE.onrender.com/api/v1/status | jq .

# 3. Haqiqiy chat so'rovini sinash
curl -X POST https://YOUR-SERVICE.onrender.com/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "bitim 100001"}' | jq .

# 4. Brauzerda ochish
# https://YOUR-SERVICE.onrender.com/
```

---

## 6. Tashqi Wake-Up Monitoring Sozlash (External Keep-Alive)

Render Free Tier 15 daqiqa davomida so‘rov bo‘lmasa konteynerni to‘xtatadi (Spin-down). Uyqudan uyg‘onish (Cold-start) taxminan 30–50 soniya vaqt olishi mumkin.

Buning oldini olish uchun bepul tashqi uptime-monitoring xizmatidan foydalaning (masalan, [UptimeRobot](https://uptimerobot.com/), [Better Uptime](https://betterstack.com/) yoki [Cron-Job.org](https://cron-job.org/)):

### Sozlash parametrlari:
- **Monitor Type**: `HTTP(s)`
- **Friendly Name**: `UZEX AI Health Check`
- **URL**: `https://YOUR-SERVICE.onrender.com/health`
- **Monitoring Interval**: `5 minutes` (har 5 daqiqada bir marta)
- **HTTP Method**: `GET`
- **Expected Status**: `200`

### ⚠️ Muhim Cheklovlar va Ogohlantirishlar:
1. **Faqat `/health` manzilini chaqiring**: Bu endpoint SQL bajarmaydi, Gemini API kvotasini sarflamaydi, xotirani band qilmaydi va minimal trafik iste’mol qiladi.
2. **Oylik 750 soat kvotasi**: Render Free hisobida bitta bepul xizmat uzluksiz 744 soat (31 kun) ishlashi mumkin. Agar hisobingizda 2 ta bepul xizmat bo‘lsa, 750 soat ikkalasiga bo‘linadi va oy oxirida kvota tugab to‘xtashi mumkin.
3. **Kafolatlanmagan doimiylik**: Render Free haftada yoki oyda kamida bir necha marta yangilanishlar tufayli konteynerni qayta yuklashi (restart) tabiiy.
4. **Self-ping loop qilmang**: Ilova ichiga o‘z-o‘zini chaqiruvchi fon taymeri qo‘shilmagan (bu arxitekturaga zid va xotirani oqdiradi).

---

## 7. Nosozliklarni Bartaraf Etish (Failure Recovery)

- **Xizmat 502 / 503 bersa**:
  Render Dashboard-da **Logs** bo‘limini oching. Agar `GEMINI_API_KEY` yoki `GEMINI_MODEL` kiritilmagan bo‘lsa, production talabiga binoan xizmat xavfsiz to‘xtaydi (`startup_failed`). Kalitlarni to‘g‘ri kiriting.
- **Out of Memory (OOM)**:
  Bizning arxitekturamizda DuckDB xotirasi 128 MB bilan qulflangan, ilovaning o‘zi esa ~160 MB RAM iste’mol qiladi. Shuning uchun 512 MB li Render Free-da OOM xavfi mavjud emas.
- **Baza yo‘qolishi (Database Loss)**:
  `uzex.duckdb` bazasi Docker imijining ichiga kiritilgan (statik read-only artefakt). Konteyner necha marta qayta ishga tushsa ham 500 000 ta bitim hech qachon yo‘qolmaydi va qaytadan yuklashni talab qilmaydi.

