# Render backend va Vercel frontend

Ushbu checkout Git ildizi `/home/doston/Desktop`; loyiha repozitoriyada
`UZEX/uzex-ai` ichida. Boshqa Desktop loyihalarini commit qilmang.

## Render Free

GitHub ombori: `CoderQudratov/UZEX-AI`. Bitta Web Service yarating:

- Branch: `main` (haqiqiy tarmoq nomini tekshiring).
- Root Directory: `UZEX/uzex-ai`.
- Language / Runtime: Docker.
- Dockerfile: `./Dockerfile`.
- Instance Type: Free.
- Health Check Path: `/health`.
- `APP_ENV=production`.
- `DATABASE_PATH=data/processed/uzex.duckdb`.
- `GEMINI_MODEL`: real API bilan tekshirilgan model identifikatori.
- `GEMINI_API_KEY`: faqat Render maxfiy Environment maydoniga kiriting.
- `MAX_CONCURRENT_QUERIES=4`.
- `GEMINI_TIMEOUT_SECONDS=20`.

`PORT`ni Render beradi; `python -m app` uni o‘qiydi. Image ichida tayyor
`data/processed/uzex.duckdb` mavjud bo‘lishi kerak. Runtime ulanishlar read-only;
`0444` fayl rejimi qo‘shimcha himoya. `.env` image yoki Gitga kiritilmaydi.

Blueprint ishlatilsa, repozitoriyadagi `UZEX/uzex-ai/render.yaml`ni tanlang.
Docker build va 512 MB limitidagi haqiqiy test bajarilmaguncha ular tasdiqlangan
deb hisoblanmaydi. Eski lokal o‘lchovlar Gemini yoki Render tezligini isbotlamaydi.

## Vercel

Xuddi shu GitHub omboridan yangi loyiha yarating:

- Root Directory: `UZEX/uzex-ai/web`.
- Framework Preset: Other.
- Build Command: bo‘sh.
- Output Directory: `.`.
- Frontend uchun API kaliti kerak emas.

`web/vercel.json` ichidagi **ikkita** Render destination hozir
`https://uzex-ai.onrender.com` qiymatiga tayyorlangan. Bu domenning xizmatga
tegishliligi deployment vaqtida tekshiriladi; Render boshqa URL bersa, ikkala
qiymatni o‘sha URLga almashtirib push qiling. Bu hujjat domen ishlayotganini
bildirmaydi.

Brauzer faqat Vercel bilan same-origin `/api/v1/*` orqali gaplashadi. Vercel
rewrite so‘rovni Renderga uzatadi. Shu sababli wildcard CORS yoki frontendda
API kaliti talab qilinmaydi. `/static/app.js` va `/static/style.css` yo‘llari
ikkala hostingda ham bir xil qoladi. Javoblarni CDNda saqlamang.

## Yakuniy tekshiruv

Renderning haqiqiy URLida `/`, `/health`, `/api/v1/status`,
`POST /api/v1/chat`, `POST /api/v1/chat/stream`ni tekshiring. O‘zbek lotin,
o‘zbek kirill va rus tilidagi haqiqiy Gemini savollarini SQL oracle bilan
solishtiring. Vercel sahifasi ham shu backendga murojaat qilishini tekshiring.
Kalit, savol, javob, prompt yoki SQL parametrlarini logga yozmang.

Savol va tegishli cheklangan sxema/nomzodlar Gemini APIga inference uchun
uzatiladi. Provayderning zero-retention kafolati bor deb da’vo qilinmaydi.

Tashqi monitoring: `GET https://HAQIQIY-XIZMAT.onrender.com/health`, har 5 daqiqa.
Bu endpoint har so‘rovda DB yoki Gemini chaqirmaydi va chat ma’lumotini saqlamaydi.
Ilova ichiga self-ping qo‘shilmaydi. Render Free uyquga ketishi mumkin; doimiy
ishlash yoki zero-downtime kafolatlanmaydi.
