# Phase 2 — Data Warehouse and Integrity

Sana: 2026-11-05, Asia/Tashkent. Loyiha: `/home/doston/Desktop/UZEX/uzex-ai`.
Holat: **PASS**. Phase 3 boshlanmadi.

## 1. Bajarilgan ishlar

Manba ZIP ichidagi to‘liq README va barcha to‘qqiz CSVning haqiqiy sarlavhalari, namunalari,
qiymat taqsimotlari va bog‘lanishlari tekshirildi. Ma’lumotlar README bo‘yicha sun’iy.

Tayyor DuckDB ombori yaratildi: deals 500 000; contracts 6 616; participants 14 392;
brokers 120; usd_rates 1 765. Qat’iy typed sxema, NOT NULL va PRIMARY KEY cheklovlari bor.
Manba summalari floatga o‘tkazilmaydi. STIR/INN, TN VED va broker kodlari VARCHAR bo‘lib
qoladi; yetkazilgan miqdordagi bo‘sh qiymatlar NULL sifatida saqlanadi.

69 ta builder yaxlitlik tekshiruvi o‘tdi. Barcha FK coverage va alohida join cardinality
tekshiruvidan keyingina `deals_enriched` yaratildi; u 500 000 noyob bitimni saqlaydi.
Shartnoma valyutasi, savdo sanasidagi USD kursi, fizik hajm va yetkazilgan hajm hisoblari
aniq turlarda. Bekor qilingan 33 719 ta va qisman bajarilgan 22 648 ta bitim alohida holatda
saqlangan, avtomatik olib tashlanmagan.

Birlik narxining aniq surat/maxraji mavjud. Alohida `unit_price_rounded_8` maydoni
DECIMAL(38,8), HALF_UP bilan, faqat integer arifmetikada hisoblanadi. Bu aniq cheksiz
kasrning o‘rnini bosmaydi. DuckDB decimal bo‘lishi float qaytarishi sababli odatiy `/`
financial view hisoblarida ishlatilmadi.

Runtime: faqat read-only, har lease uchun alohida connection/cursor, bounded concurrency,
bir soniyalik capacity kutish, 5 soniyalik absolute lease deadline, interrupt, 128 MB DuckDB
budjeti, bir worker thread, disk spill taqiqi, external access/extension/logging taqiqi,
locked configuration. Xatolar SQL, yo‘l va kiruvchi ma’lumotni oshkor qilmaydi. Baza fayli
0444 ruxsatga ega. `/health` bazaga ulanmasdan ishlashda davom etadi.

## 2. Yaratilgan yoki o‘zgartirilgan fayllar

- `scripts/build_database.py` — talab qilingan offline build CLI.
- `app/db/build.py` — qat’iy CSV import, fingerprint, katalog va atomic publication.
- `app/db/schema.py` — haqiqiy Russian→English sxema va metadata konstantalari.
- `app/db/integrity.py` — 69 ta yaxlitlik tekshiruvi.
- `app/db/runtime.py` — read-only, parallel xavfsiz, chegaralangan ulanishlar.
- `app/db/source_regions.json` — manbada tasdiqlangan 14 ta hudud mosligi.
- `data/processed/uzex.duckdb` — tayyor checkpoint qilingan baza, WAL yo‘q.
- `data/processed/schema_catalog.json` — barcha ustun xaritalari, turlar, statuslar,
  valyuta/sana/birlik semantikasi, join allowlist, manba/CSV/logical checksum va versiya.
- `data/processed/build_report.json` — haqiqiy build natijalari va timings.
- `tests/unit/test_warehouse_import.py`, `tests/integration/test_warehouse.py`,
  `tests/conftest.py` — import/yaxlitlik/runtime/original-source testlari.
- `scripts/benchmark_warehouse.py`, `docs/warehouse_performance.json` — haqiqiy o‘lchovlar.
- `docs/database-design.md` — to‘liq mapping va loyiha chegaralari.
- `README.md`, `docs/architecture.md`, `.gitignore`, ushbu hisobot.

Qo‘shimcha dependency qo‘shilmadi, `uv.lock` o‘zgarmadi. Extra indeks yoki materialized summary
qo‘shilmadi; PRIMARY KEY uchun zarur avtomatik ART indekslari bor.

## 3. Haqiqatan bajarilgan asosiy buyruqlar

Ish papkasi: `/home/doston/Desktop/UZEX/uzex-ai`.

```bash
.venv/bin/python scripts/build_database.py --archive /home/doston/Downloads/uzex_spot_data.zip
.venv/bin/python -m pytest -q -c pyproject.toml tests --source-archive=/home/doston/Downloads/uzex_spot_data.zip
.venv/bin/python scripts/benchmark_warehouse.py
.venv/bin/ruff check --fix --output-format concise .
.venv/bin/ruff format .
.venv/bin/ruff check --output-format concise .
.venv/bin/ruff format --check .
/tmp/uzex-foundation-tools/bin/uv lock --check
```

Qo‘shimcha Python tekshiruvlarida ZIP tarkibi va to‘liq README o‘qildi, kategoriyalar sanaldi,
DuckDB sozlamalari va taqiqlari bevosita tekshirildi, artifact SHA-256 qayta hisoblandi.
Vaqtinchalik Git metadata bilan `git check-ignore --no-index` orqali final uch artifact
ignore qilinmasligi, `.env`/raw ZIP/WAL esa chetda qolishi haqiqatan tekshirildi. Loyiha uchun
Git commit/push yoki deploy bajarilmadi.

## 4. Testlar va topilgan xatolar

Yakuniy to‘liq suite: **77 PASS, 0 FAIL, 0 warning — 39.59 s**.
Ruff: **PASS**, 27 Python fayli format tekshiruvidan o‘tdi. Lockfile freshness: **PASS**.

Qamrov:

- Aniq countlar, unique/non-null PKlar, barcha FK va joinlar, 500 000 enriched row.
- Original ZIPning **har bir mapped ustuni**, jumladan 500 000 bitim, mustaqil Python typed
  parseri bilan oqim usulida bazaga solishtirildi.
- Valyutalar bo‘yicha alohida aniq summalar, USD→UZS umumiy nazorat summasi, status sonlari,
  birliklar bo‘yicha fizik/yetkazilgan hajmlar, NULL yetkazish soni mustaqil hisob bilan mos.
- Tanlangan bitimlarda birlik narxi mustaqil Python Decimal HALF_UP hisobiga mos;
  enriched viewda DOUBLE/FLOAT maydoni yo‘q.
- Noto‘g‘ri moliyaviy format, ortiqcha decimal scale, NaN, exponent, noto‘g‘ri sana/vaqt,
  ID injection matni, noto‘g‘ri INN, header xatosi va checksum xatosi rad etildi.
- Boshlang‘ich nollari bor STIR va NULL qiymatlar saqlandi.
- UPDATE/DELETE/CREATE, tashqi fayl o‘qish/yozish, ATTACH, INSTALL/LOAD va xavfli
  konfiguratsiya o‘zgarishlari taqiqlandi. COPY chiqish fayli yaratilmadi.
- 4 parallel worker bilan 12 o‘qish bir xil natija berdi, capacity chegarasi va qayta
  ishlatilishi tekshirildi.
- Yo‘q baza yaratilmaydi; ikki alohida process/restartdan keyin baza o‘qiladi;
  SHA-256, mtime va katalogdagi fayllar ro‘yxati o‘zgarmadi.
- Memory overflow spill yaratmasdan rad etildi. Deadline aktiv queryni to‘xtatadi va
  muddati o‘tgan idle lease keyingi queryni boshlamaydi; capacity qaytariladi.
- Ikkinchi to‘liq build bir xil logical/source checksum berdi va vaqtinchalik xom CSVlar
  tozalandi. Noto‘g‘ri source bilan build mavjud artifactni o‘zgartirmaydi.

Dastlabki ikki build urinishida DuckDB API mosligi xatolari topildi: `enable_logging`
connection ochilishidan oldin o‘rnatilmaydi, Python dict esa avtomatik STRUCTga bind bo‘ladi.
Logging ochilgandan keyin o‘chirildi; region mapping aniq MAP sifatida bind qilindi.
Shundan so‘ng builder to‘liq o‘tdi. Birinchi to‘liq suite 74 PASS / 1 FAIL edi: barcha
500 000 keng satrni sort qilish 128 MB runtime limitidan oshdi. Asosiy sabab bevosita
OutOfMemoryException bilan tasdiqlandi. Full-source offline tekshiruvga alohida 512 MB
budjet berildi, runtime limiti oshirilmadi. Bu holat uchun fail-closed/no-spill testi qo‘shildi.
Deadline joriy etilgach yakuniy 77 test qayta to‘liq bajarildi.

## 5. Qolgan aniqlik va xavfsizlik xatarlari

- Render/Docker build/run bu kompyuterda sinalmagan: Docker o‘rnatilmagan. Git va Docker
  ignore qoidalari yakuniy bazani chiqarib tashlamaydi, lekin bu haqiqiy image build o‘rnini
  bosmaydi. Renderga deploy qilinmadi.
- Runtime xotira limiti katta to‘liq natija/saralashlarni rad etishi mumkin; Phase 3 typed
  query compileri ruxsat etilgan ustunlar, operatsiyalar va qat’iy natija limitlarini qo‘llashi
  kerak. DuckDB xotira sozlamasi butun Python process RSS limiti emas.
- Read-only konfiguratsiya himoya qatlami; arbitrary user SQLga ruxsat berilmaydi. Hozir
  umumiy SQL/agent HTTP endpointi yo‘q. Fayl yo‘llari faqat deployment/builder parametrlaridan.
- Build service to‘xtatilgan paytda bajarilsin; DB/catalog/report alohida atomik fayllar,
  ko‘p faylli transactional rollout mexanizmi emas.
- Tarjima, mahsulot aliaslari, aniqlashtirish, LLM rejasi, prompt injection, frontend va
  savol hajmi limiti keyingi bosqichlarga tegishli. Bu bosqich ularni amalga oshirmadi.
- Barcha manba ma’lumotlar sun’iy, snapshot 30.10.2026. Bo‘sh yetkazish qiymatlari noma’lum;
  cancelled/partial bitimlar hisobga olinishi aynan savol semantikasiga bog‘liq.
- User savoli/javobi/rejasi/tarixi bazaga yoki logga yozilmaydi. Test va build hisobotlari
  faqat authoritative dataset va texnik o‘lchovlar haqidadir. Gemini hali chaqirilmadi;
  kelajakda inference savolni Googlega yuboradi, third-party zero retention va’da qilinmaydi.

## 6. Haqiqiy hajm va tezlik

- Tayyor baza: **29,896,704 bayt = 28.51172 MiB**.
- Build/import + validation + logical fingerprint + checkpoint: **13.22844 s**
  (reportning publicationdan oldingi o‘lchovi; yakuniy fayl rename/JSON yozish qismi qo‘shilmagan).
- Deals import: **4.476988 s**.
- Validation: **0.507862 s**.
- Logical fingerprint: **7.875651 s**.
- Physical artifact SHA-256: `f934cbc5227c8322fc34b6fdcbda4a5cd2c9267c4bbaf837b80c0a63679f43f5`.
- Source ZIP SHA-256: `88182bf4dad3569eea5fac611e8a16db7a455110fdaa6495650e7d87e09ac258`.
- Logical dataset SHA-256: `e9f17cd418b009797b90b3962ae1464156b4eef31421fd07d1ee8ea3c01c8eb5`.

Har operatsiya uchun 3 warm-up va 30 ketma-ket sample. Har sample yangi read-only lease va
connection ochish/yopishni o‘z ichiga oladi. p50 — median, p95 — nearest-rank.

| Fixed integrity read | p50, ms | p95, ms |
| --- | ---: | ---: |
| row_count | 10.985 | 12.461 |
| primary_key_lookup | 12.132 | 13.776 |
| currency_reconciliation | 82.495 | 85.672 |

Bu lokal, OS fayl keshi iliq sharoitdagi ombor tekshiruvi. Render, HTTP, Gemini, real user
savoli yoki parallel yuklama benchmarki emas. Bunday ko‘rsatkichlar ixtiro qilinmadi.

## 7. Phase 3 uchun tayyor prompt

> PHASE 3 — DETERMINISTIC QUERY ENGINE. UZEX master ko‘rsatmalariga rioya qiling. Loyiha: `/home/doston/Desktop/UZEX/uzex-ai`. Avval README, docs/architecture.md, docs/database-design.md, docs/phase-2-report.uz.md va data/processed/schema_catalog.json fayllarini o‘qing. Tasdiqlangan read-only DuckDB bazasi ustida Pydantic v2 strict query plan va deterministik SQL compiler yarating. Jadval/ustun/join/metric/operator/sort ro‘yxatlari allowlist bo‘lsin, barcha qiymatlar typed parametrlar orqali bind qilinsin. User/LLM SQLi yoki fayl yo‘li qabul qilinmasin. Exact-ID lookup va cheklangan filter/aggregate/group/sort/top-k so‘rovlarini qo‘llang. UZS/USD, birliklar, snapshot/status semantikasi va NULL qiymatlarni saqlang; taxminiy mahsulot/company birlashtirish qilmang. Birlik narxida floatdan saqlaning, rounding siyosatini aniq belgilang. ReadOnlyWarehouse concurrency, memory/no-spill va deadline himoyalarini ishlating. Natija hajmi va plan murakkabligini qat’iy cheklang. OK, NOT_FOUND, AMBIGUOUS, UNSUPPORTED va ERRORni farqlang; yetarli dalil bo‘lmasa fail closed qiling. To‘g‘ri va noto‘g‘ri planlar, SQL/prompt-injectionga o‘xshash qiymatlar, aralash valyuta/birlik, bekor/qisman bitimlar, timeout va natija limitlari uchun haqiqiy unit/integration/golden testlar yozing. Hozircha Gemini integratsiyasi yoki frontend yozmang. Muhim testlar o‘tmaguncha keyingi bosqichga o‘tmang. Yakunda yetti bandli o‘zbekcha hisobot va haqiqiy p50/p95 ko‘rsatkichlarini bering; Phase 3 tugagach to‘xtang.
