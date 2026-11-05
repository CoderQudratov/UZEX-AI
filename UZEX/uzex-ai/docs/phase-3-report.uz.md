# Phase 3 — Deterministic Query Engine

Sana: 2026-11-05, Asia/Tashkent.
Loyiha: `/home/doston/Desktop/UZEX/uzex-ai`.
Holat: **PASS**. Gemini chaqirilmadi, frontend yoki yangi HTTP query endpointi yaratilmadi.
Phase 4 boshlanmadi.

## 1. Bajarilgan ishlar

Qat’iy Pydantic QueryPlan → semantik validator → deterministik SQL compiler → read-only
executor → VerifiedResult oqimi amalga oshirildi. Transaction/contract/company STIR/broker
lookup, transaction count, delivered count, summa, aniq arifmetik o‘rtacha, min/max,
seller/buyer/product/broker reytinglari, sana/oy guruhlari, status va product-code filtrlari,
UZS/USD, ikki davrning yonma-yon taqqoslanishi, partial delivery va ko‘p filtrli so‘rovlar bor.

Shartnomaning alohida status ustuni manbada yo‘q: bunday reja **UNSUPPORTED /
CONTRACT_STATUS_ABSENT** qaytaradi. Uning o‘rniga bitim statusi yoki shartnoma turi
qo‘yilmadi. Shartnoma turi va shakli haqiqiy ustunlar bilan filtrlanadi. Taqqoslash ikki
aniq, kesishmaydigan inclusive davr natijalarini beradi; yo‘q guruh/davrga nol summa yoki
taxminiy growth foizi qo‘shilmaydi.

Jadvallar, ustunlar, metric/dimension/operator/sort/lookup/joinslar allowlist bilan
cheklangan. Filter qiymatlari bind parametrlar. Input SQL, expression, arbitrary alias yoki
LLM boshqaradigan yo‘l qabul qilinmaydi. Oddiy so‘rovlarda kerak bo‘lmagan participant/broker
joinlari ishlatilmaydi.

Entity lug‘ati faqat haqiqiy bazadan: **14 392 kompaniya, 120 broker, 230 mahsulot yozuvi,
40 TN VED kodi, 14 hudud, 8 bitim statusi**. Uzbek Latin/Cyrillic va Russian normalizatsiya,
transliteratsiya, tekshirilgan hudud/status aliaslari va cheklangan mahsulot tarjimalari bor.
RapidFuzz variantlari doim tasdiq so‘raydigan AMBIGUOUS bo‘ladi; identifier fuzzy qilinmaydi.
Bir xil normalizatsiyalangan nomga bir nechta ID mos kelsa tasodifiy tanlov yo‘q.

Natija statuslari VERIFIED / NOT_FOUND / AMBIGUOUS / UNSUPPORTED / ERROR. Rows, row_count,
aggregate ma’nolari, asl valyutalar, birliklar, typed filtrlar, source evidence va dataset
versiyasi kiritilgan. Executable audit SQL parametrlar bilan **faqat RAMda**, oddiy JSON va
reprdan chiqarilgan. Savol/plan/javob/history uchun log, fayl yoki doimiy cache qo‘shilmadi.

## 2. Yaratilgan va o‘zgartirilgan fayllar

Talab qilingan yettita modul:

- `app/agent/query_models.py`
- `app/agent/query_validator.py`
- `app/agent/query_compiler.py`
- `app/agent/query_executor.py`
- `app/agent/entity_resolver.py`
- `app/agent/evidence.py`
- `app/agent/answer_formatter.py`

Qo‘shimcha:

- `tests/unit/test_query_validation.py`
- `tests/integration/test_query_engine.py`
- `tests/golden/test_answer_templates.py`
- `scripts/benchmark_query_engine.py`
- `docs/query-engine.md`, `docs/query_plan.schema.json`
- `docs/query_engine_performance.json`, ushbu hisobot
- `README.md`, `docs/architecture.md`

Yangi dependency qo‘shilmadi; lockfile va tayyor database o‘zgarmadi. Bazaning fizik SHA-256
build report bilan qayta solishtirildi va aynan mosligi tasdiqlandi; WAL/spill topilmadi.

## 3. Haqiqatan bajarilgan buyruqlar

```bash
.venv/bin/python -m pytest -q tests/integration/test_query_engine.py
.venv/bin/python -m pytest -q tests/unit/test_query_validation.py tests/golden tests/integration/test_query_engine.py
.venv/bin/python -m pytest -q -c pyproject.toml tests --source-archive=/home/doston/Downloads/uzex_spot_data.zip
.venv/bin/python scripts/benchmark_query_engine.py
.venv/bin/ruff check --fix --output-format concise .
.venv/bin/ruff format .
.venv/bin/ruff format docs/query-engine.md
.venv/bin/ruff check --output-format concise .
.venv/bin/ruff format --check .
/tmp/uzex-foundation-tools/bin/uv lock --check
.venv/bin/python -m compileall -q app scripts tests
```

Qo‘shimcha bajarilgan Python tekshiruvlari: source schema va catalogni o‘qish; haqiqiy
mahsulot qiymatlarini ko‘rish; parallel DuckDB xatosining asl sababini bevosita tekshirish;
uch tildagi deterministik formatni tekshirish; entity lug‘ati hajmlarini sanash; artifact
SHA-256ni qayta hisoblash. Gemini/API yoki frontend ishlatilmadi.

## 4. Haqiqiy test natijalari

**Yakuniy to‘liq suite: 141 PASS, 0 FAIL, 0 warning — 43.01 soniya.**
Shundan 64 tasi Phase 3 qo‘shimcha testlari; oldingi 77 test ham qayta o‘tdi.
Ruff check, formatter, lockfile freshness va compile tekshiruvlari **PASS**.

Mustaqil direct SQL oracle bilan: count, delivered count, original/converted SUM, MIN/MAX,
arifmetik transaction mean, TOP-N seller/buyer/product/broker, barcha lookup turlari,
sana chegaralari va monthly grouping, ikki davr, TN VED, contract type/form, cancellation
va partial delivery tekshirildi. Vaznli narx/min-max quote mustaqil Python Decimal bilan
solishtirildi. Bir plan uch takror va to‘rtta parallel ishda barqaror natija berdi.

Salbiy testlar: invalid field/operator ma’nosi, identifier/string type, nonfinite/overflow,
SQL-injection literal qiymati, unchecked model bypass, request/group/response limitlari,
noto‘g‘ri price/currency/unit talqini, fuzzy/nom to‘qnashuvi, yo‘q ID/davr, timeout, ichki
xato, artifact o‘zgarishi va audit SQLning public JSONga chiqmasligi. Golden testlar uch
til/yozuvdagi xavfsiz status matnlarini aynan solishtiradi.

Dastlab 24 PASS / 4 FAIL bo‘ldi: independent oracle joinida lot_size aliasi noaniq edi;
injection testi natijadagi so‘ralgan filter evidence bilan public answer formatini
aralashtirgan; NaN Pydantic tomonidan executiondan oldin rad etilgan; parallel probes
ortiqcha join/distinct state sababli 128 MB limitiga sig‘magan. Sabablar alohida tekshirildi.
Oracle `d.lot_size` bilan aniqlashtirildi, filter evidence saqlandi va injection matni
formatterga chiqmasligi tekshirildi, NaN uchun validation rejection testi qo‘yildi,
compiler esa minimal join/probe bilan tuzatildi. Runtime xotira chegarasi oshirilmadi.

Keyingi fuzzy testi RapidFuzzga set qiymatli dict berilganini aniqladi: rasmiy APIga mos
ravishda qidiruv normalizatsiyalangan string kalitlar tuple’i ustida ishlaydi. Malformed
model serializatsiyasidagi payload-bearing warninglar `warnings="error"` orqali xavfsiz
rad etishga aylantirildi. Tuzatishlardan so‘ng to‘liq suite qayta bajarildi.

## 5. Qolgan aniqlik va xavfsizlik xatarlari

- Bu structured engine: tabiiy til, colloquial Uzbek, to‘liq misspelling interpretation va
  suhbat semantikasi hali yo‘q. Ular Phase 4 ga tegishli. Alias lug‘ati cheklangan;
  topilmagan sinonimga taxminiy moslik majburlanmaydi.
- Datasetda contract_status yo‘q. Uning ustida qo‘llab-quvvatlangan hisob da’vo qilinmadi.
- Product ranking recorded name asosida; bu canonical product family emas. Bir xil nomli
  kompaniyalarni korporativ identity deb birlashtirmaslik uchun INN, brokerlarda code
  ishlatilsin; grouping by name aynan recorded string ma’nosida.
- Unit price ratio qiymatlari 8 kasr xonasigacha HALF_UP; bu takrorlanuvchi kasrning aniq
  cheksiz ifodasi emas. `avg_amount` transaction sum mean, weighted price emas.
- 128 MB engine budjeti va 5 soniyalik lease chegarasi katta/parallel operatsiyani ERROR
  bilan rad qilishi mumkin. Hozirgi testdagi parallel so‘rovlar o‘tdi; bu barcha yuklamalar
  uchun throughput yoki Render kafolati emas.
- Docker/Render bu kompyuterda sinalmagan, deploy bajarilmadi. HTTP query endpointi ham
  yaratilmagan; keyingi API request byte limitini va frontend text escapingni ta’minlasin.
- Dataset snapshot 30.10.2026, ma’lumotlar sun’iy. Factual javoblar faqat shu snapshotga tegishli.
- SQL, parametr, filter va natijalarni keyingi integration logga yozmasin. Gemini keyingi
  bosqichda savolni Googlega yuboradi; third-party zero retention va’da qilinmaydi.

## 6. Haqiqiy p50/p95

Har operatsiya: 3 warm-up, keyin 30 ketma-ket sample; p50 median, p95 nearest-rank.

| Operatsiya | p50, ms | p95, ms |
| --- | ---: | ---: |
| exact_lookup | 22.566 | 23.893 |
| aggregation | 59.331 | 61.927 |
| ranking | 73.603 | 75.741 |
| multi_table_join | 43.266 | 46.340 |

Bir martalik initialization: **257.735 ms**. Sample vaqtlariga u kirmaydi.
Samplelarda validation, artifact stat guard, semantik probes, compilation, connection
lifecycle, SQL execution, exact arithmetic, sort va VerifiedResult tekshiruvi bor.
Formatting, Gemini va HTTP yo‘q. Lokal warm OS file cache ishlatilgan; Render yoki real
foydalanuvchi end-to-end latency qiymatlari ixtiro qilinmadi. Benchmark faqat aggregate
timinglarni saqlaydi, query/plan/params/javoblarni emas.

## 7. Phase 4 uchun tayyor prompt

> PHASE 4 — GEMINI SEMANTIC UNDERSTANDING ENGINE. UZEX master engineering ko‘rsatmalariga rioya qiling. Loyiha: `/home/doston/Desktop/UZEX/uzex-ai`. Avval README, docs/query-engine.md, docs/query_plan.schema.json va docs/phase-3-report.uz.md fayllarini o‘qing. Rasmiy google-genai SDK va envdagi Gemini Flash modeli bilan foydalanuvchi savolidan qat’iy QueryPlan yaratuvchi semantic engine qo‘shing. Faqat Uzbek Latin, Uzbek Cyrillic va Russianni qo‘llang; Cyrillicni avtomatik Russian deb olmang. Unsupported tilda factual savolga javob bermang. Colloquial grammar, misspellings, abbreviations, rol/date/currency/unit/price ambiguity va injectionni xavfsiz boshqaring. Murakkab so‘rovda odatda bitta structured JSON planning chaqiruvi bo‘lsin. Gemini SQL yoki sonli factual javob yaratmasin; reja mavjud validator/compiler/executor va deterministik formatterdan o‘tsin. Noaniq entity yoki talqinda aniqlashtirish qaytaring; source contract_status yo‘qligini hurmat qiling. API key faqat server envda bo‘lsin. Timeout/concurrency/retry budjetlarini cheklang; payload logging, telemetry, persistent history/cache bo‘lmasin. Savol Googlega inference uchun yuborilishini hujjatlashtiring va third-party zero retentionni kafolatlamang. Haqiqiy kalit mavjud bo‘lsa cheklangan real integratsiyani sinang; bo‘lmasa offline/mock test va real API sinovini aniq ajrating, real success yoki latency ixtiro qilmang. Uch til/yozuv, adversarial input va xato-statuslar uchun testlar yozing, to‘liq suite’ni bajaring. Hozircha frontend yoki deployga o‘tmang. Phase 4 tugagach to‘xtang, yetti bandli o‘zbekcha hisobot va keyingi promptni bering.
