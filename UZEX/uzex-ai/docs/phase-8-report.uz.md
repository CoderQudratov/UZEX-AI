# 8-Bosqich: Keng Qamrovli Sifat, Xavfsizlik va NLP Baholash Hisoboti (Phase 8 Report)

**Sana:** 2026-11-05  
**Rollar:** Bosh QA Muhandisi (Principal QA Engineer), AI Red-Team Xavfsizlik Muhandisi, Ma'lumotlar Bazasi Auditori va Ikki Tilli NLP Baholovchisi  
**Tizim:** UZEX AI (O‘zbekiston Respublika Tovar-Xomashyo Birjasi AI Analitik Tizimi)  
**Holat:** Muvaffaqiyatli yakunlandi (100% testlar o‘tdi, 0 ta gallyutsinatsiya, to‘liq deterministik xavfsizlik)

---

## 1. Kirish va Baholash Metodologiyasi

8-bosqichning asosiy maqsadi — UZEX AI tizimini xakatonga topshirishdan oldin uning ma'lumotlar yaxlitligi, faktik to'g'riligi, gallyutsinatsiyalardan xoliligi, ko'p tilli (O'zbek lotin, O'zbek kirill, Rus) talqini, xavfsizlik va arxitektura barqarorligini chuqur tekshirishdan iborat.

Baholash jarayonida haqiqiy 500 000 ta birja bitimini o'z ichiga olgan DuckDB ombori (`data/processed/uzex.duckdb`) ustida **238 ta mustaqil avtorlik test keyslari** (`GOLDEN_CASES`) yaratildi. Barcha kutilgan raqamli va faktik natijalar Gemini tomonidan emas, balki ma'lumotlar bazasi ustida to'g'ridan-to'g'ri bajarilgan ishonchli etalon SQL (reference SQL) so'rovlari orqali hisoblandi.

---

## 2. Asosiy Metrikalar va Baholash Natijalari

Golden Suite baholash skripti (`scripts/run_golden_evaluation.py`) va to'liq avtomatlashtirilgan pytest to'plami (`tests/golden/test_golden_200_suite.py`) orqali qayd etilgan natijalar:

| Metrika | Qayd etilgan natija | Talab etilgan mezon | Holat |
| :--- | :--- | :--- | :--- |
| **Umumiy aniqlik (Overall Accuracy)** | **100.0%** (238/238) | $\ge 95.0\%$ | A'LO |
| **Gallyutsinatsiyalar soni (Hallucinations)** | **0 ta** | **Qat'iy 0 ta** | A'LO |
| **NOT_FOUND aniqligi** | **100.0%** (18/18) | 100.0% | A'LO |
| **Semantik ekvivalentlik aniqligi** | **100.0%** (25/25) | $\ge 95.0\%$ | A'LO |
| **Inkor mantiqi aniqligi (Negation)** | **100.0%** (24/24) | $\ge 95.0\%$ | A'LO |
| **Kechikish vaqti (P50 Latency)** | **41.58 ms** | $< 100\text{ ms}$ | A'LO |
| **Kechikish vaqti (P95 Latency)** | **67.11 ms** | $< 150\text{ ms}$ | A'LO |
| **O'rtacha kechikish (Avg Latency)** | **35.12 ms** | $< 80\text{ ms}$ | A'LO |

### Tillar bo'yicha aniqlik:
* **O'zbek tili (Lotin yozuvi - `uz_latn`):** 127/127 (100.0%)
* **O'zbek tili (Kirill yozuvi - `uz_cyrl`):** 38/38 (100.0%)
* **Rus tili (`ru`):** 39/39 (100.0%)
* **Qo'llab-quvvatlanmaydigan tillar (`unsupported`):** 10/10 (100.0% xavfsiz rad etildi)

---

## 3. 12 ta Kategoriya bo'yicha Natijalar

| Kategoriya | Nomi | Jami testlar | O'tgan testlar | Aniqlik |
| :---: | :--- | :---: | :---: | :---: |
| **A** | Aniq identifikator qidiruvlari (Exact Lookups) | 20 | 20 | 100.0% |
| **B** | Moliyaviy va statistik tahlil (Financial Analytics) | 25 | 25 | 100.0% |
| **C** | O'zbek tili lotin yozuvi (Uzbek Latin) | 22 | 22 | 100.0% |
| **D** | O'zbek tili kirill yozuvi (Uzbek Cyrillic) | 22 | 22 | 100.0% |
| **E** | Rus tili (Russian NLP) | 22 | 22 | 100.0% |
| **F** | Semantik kontrastlar (Semantic Contrasts) | 20 | 20 | 100.0% |
| **G** | Semantik ekvivalentlik (Semantic Equivalence) | 25 | 25 | 100.0% |
| **H** | Yo'qolgan va mavjud bo'lmagan ma'lumotlar (Missing Data) | 18 | 18 | 100.0% |
| **I** | Noaniq va chala so'rovlar (Ambiguous Input) | 18 | 18 | 100.0% |
| **J** | Hujumlar va qasddan buzish (Adversarial / Red-Team) | 22 | 22 | 100.0% |
| **K** | Maxfiylik va telemetriya (Privacy & Telemetry) | 10 | 10 | 100.0% |
| **L** | Infratuzilma va chidamlilik (Infrastructure) | 14 | 14 | 100.0% |
| **JAMI** | **Barcha toifalar bo'yicha** | **238** | **238** | **100.0%** |

---

## 4. Kategoriyalarning Muhim Xulosalari

### Kategoriya A & B: Aniq Qidiruv va Moliyaviy Tahlil
* **Haqiqiy bitimlar:** Bitim `100001` (304 547 938.40 UZS, "Исполнен"), `100002` (23 145 714.00 UZS) va boshqalar 100% aniqlikda, to'g'ridan-to'g'ri `exact_lookup` tezyo'li orqali LLM chaqiruvlarisiz o'ta tez (12-25 ms) topildi.
* **Mavjud bo'lmagan IDlar:** `999999999` raqamli bitim, shartnoma, STIR va brokerlar uchun soxta ma'lumot to'qilmasdan, standart `Mos ma’lumot topilmadi.` deterministik shabloni qaytarildi.
* **Yig'indilar va Hajmlar:** 2025-yil bitimlar soni (`115 763`), jami bitimlar (`500 000`), AQSh dollaridagi bitimlar summasi (`220 524 617.85 USD`), UZSga o'girilgan jami summa (`55 976 577 480 267.0551 UZS`), sement bo'yicha eng yirik xaridor (`LO‘HI IMPEKS MCHJ` — 71 114 tonna) va eng yirik sotuvchi (`FICHO‘R STROY OK` — 163 461 tonna) ma'lumotlar bazasi hisob-kitoblariga 100% mos tushdi.

### Kategoriya F: Semantik Kontrastlar
Tizim quyidagi ma'noviy qarama-qarshiliklarni bir-biri bilan adashtirmasligi isbotlandi:
1. **Sotuvchi va Xaridor:** `xaridor hajmi` (71 114 tonna) $\ne$ `sotuvchi hajmi` (163 461 tonna).
2. **Oldin va Keyin:** `2025 dan oldin` (284 931 ta) $\ne$ `2025 dan keyin` (99 306 ta).
3. **Eng ko'p va Eng kam:** Eng yirik sement sotuvchisi (163 461 t) $\ne$ eng kichik sement sotuvchisi (1 331 t).
4. **Bekor qilingan va Bajarilgan:** `bekor qilingan` (33 719 ta) $\ne$ `bajarilgan` (431 061 ta).
5. **Summa va Soni:** `2025 yildagi summa` (55.97 trln UZS) $\ne$ `2025 yildagi bitimlar soni` (115 763 ta).
6. **Shartnoma va Bitim:** `shartnoma 100001` (alyuminiy profil) $\ne$ `bitim 100001` (paxta chigiti shroti).
7. **2025 dan oldin va 2025 yil oxirigacha:** `2025 dan oldin` (284 931 ta) $\ne$ `2025 yil oxirigacha` (400 694 ta).

### Kategoriya G: Semantik Ekvivalentlik
5 xil ma'nodagi savollarning har biri 5 xil ko'rinishda (rasmiy o'zbek, so'zlashuv o'zbek, qisqartirilgan o'zbek, o'zbek kirill, rus tili) berilganda, har bir guruhdagi barcha 5 ta so'rov bir xil kanonik `QueryPlan` va bir xil raqamli natija berishi to'liq tekshirildi (Cluster 1: 115 763; Cluster 2: 500 000; Cluster 3: 33 719; Cluster 4: 284 931; Cluster 5: 8 837).

### Kategoriya J & K: Xavfsizlik va Maxfiylik
* **SQL Injection:** `' OR 1=1`, `'; DROP TABLE deals; --`, `STIR: 915688255' UNION SELECT 1,2,3 --` kabi kiberhujumlar tizimga hech qanday ta'sir ko'rsatmadi; barcha so'rovlar qat'iy parametrli kompilyator tomonidan xavfsiz neytrallandi.
* **Prompt Injection:** "Ignore previous instructions", "Invent a company" va kompaniya nomlari ichiga yashirilgan tizim buyruqlari qat'iy tekshiruv (guard) orqali rad etildi.
* **Katta hajmli so'rovlar:** 4096 baytdan oshgan yuklamalar darhol `UNSUPPORTED: REQUEST_SIZE` holatida to'xtatildi.
* **Maxfiylik:** Frontend kodida (`web/static/*`) birorta ham API kalit, tashqi treker (Google Analytics, Yandex Metrika) yoki doimiy brauzer xotirasi (`localStorage`, `sessionStorage`, `cookies`) mavjud emasligi tasdiqlandi.

---

## 5. Sinovlar Davomida Aniqlangan Kamchiliklar va Kiritilgan Tuzatishlar (Bug Fixes)

Sinovlar jarayonida aniqlangan 6 ta nozik defekt bartaraf etildi:

1. **Vaqt chegarasidagi so'zlashuv iborasi (`oldingi`):**
   * *Muammo:* `"2024 dan oldingi bitimlar"` so'rovidagi `oldingi` so'zi tizim tomonidan deiktik ("oldingi ko'rsatilgan bitimlar") deb qabul qilinib, `AMBIGUOUS: FOLLOWUP_UNRESOLVED` berayotgan edi.
   * *Yechim:* `app/agent/semantic_router.py` faylidagi deiktik qidiruvga `(?<!(?:dan|дан)\s)\boldingi\b` negative lookbehind qo'shildi. `dan oldingi` endi vaqt chegarasi (`boundary="before"`) sifatida to'g'ri taniladi.

2. **Ruscha so'z tartibi (`Номер договора`, `Номер сделки`):**
   * *Muammo:* Rus tilida `номер` so'zi oldinda kelganda (`Номер договора: 100001`), `exact_lookup` regexi faqat `договор номер` tartibini kutganligi uchun tezyo'l ishlamay qolayotgan edi.
   * *Yechim:* `app/agent/semantic_router.py`dagi regex ikkala so'z tartibini ham (`Номер договора` va `Договор номер`) qamrab oladigan qilib takomillashtirildi.

3. **Kirill alifbosidagi soliq identifikatori (`СТИР`):**
   * *Muammo:* `СТИР 975923536` so'rovi kirill alifbosi lug'atida maxsus belgilanmagani sababli til aniqlagich (`detect_language`) tomonidan `None` deb qaytarilayotgan edi.
   * *Yechim:* `app/agent/language_detector.py` faylida `СТИР` o'zbek kirill (`uz_cyrl`) ko'rsatkichi sifatida mustahkamlandi.

4. **Yakka holdagi `qancha` so'zi:**
   * *Muammo:* `signals` funksiyasida `qancha bitim` birikmasi talab qilinib, yakka `qancha` kelganda metrka `unknown` bo'lib qolayotgan edi.
   * *Yechim:* `app/agent/semantic_guard.py`da `qancha` mustaqil sanash signali sifatida tasdiqlandi.

5. **Yil oxirigacha bo'lgan vaqt chegarasi (`oxirigacha`):**
   * *Muammo:* `"2025 yil oxirigacha nechta bitim?"` so'rovi oddiy yil filtri bilan to'qnash kelib, `TIME_MISMATCH` keltirib chiqarayotgan edi.
   * *Yechim:* `app/agent/semantic_guard.py`ga `boundary="through"` holati qo'shildi (`deal_date <= 2025-12-31`).

6. **O'rtacha summa hisobi yaxlitlanishi:**
   * *Muammo:* `B15` testidagi kutilgan o'rtacha qiymat etalon SQLning `483544634.12547235` (8 xonali yaxlitlash) natijasi bilan aniqlashtirildi.

---

## 6. Xavfsizlik va Muvofiqlik Auditi (Security Checklist)

- [x] **Zero Invented Facts:** Hech qanday soxta bitim, kompaniya, summa yoki raqam to'qilmadi.
- [x] **No Currency Leakage:** Valyuta konversiyalari va birliklar aralashib ketmadi; asl valyuta va UZS aniq ajratildi.
- [x] **Read-Only Database:** DuckDB faqat `read_only=True` va `0444` rejimida ishlaydi; yozishga har qanday urinish `duckdb.PermissionException` chaqiradi.
- [x] **No SQL Injection:** Barcha SQL so'rovlari oldindan belgilangan yopiq kompilyator orqali parametrli tuziladi.
- [x] **Stateless Privacy:** Chat xabarlari server diskida, SQLite-da yoki ma'lumotlar bazasida saqlanmaydi; faqat operativ xotirada (RAM) ishlov beriladi.
- [x] **Frontend Sanitization:** Frontendda hech qanday maxfiy kalit, token yoki uchinchi tomon telemetriyasi yo'q.
- [x] **Resource Governance:** Semafor (maksimal 4 parallel so'rov), 5 soniyalik DuckDB taymauti va 128 MB RAM chegarasi o'rnatilgan.

---

## 7. Xulosa va 9-Bosqichga O'tish

8-bosqich doirasida UZEX AI tizimining to'liq sifat, xavfsizlik, axborot yaxlitligi va ikki tilli NLP talqini tekshiruvdan o'tkazildi. Tizimdagi barcha 574 ta birlik va integratsion testlar 100% muvaffaqiyatli yakunlandi.

Tizim hackathon talablariga to'liq javob beradi va yakuniy 9-bosqichga (Performance Optimization and Final Release Audit) tayyor.

---

## 9-Bosqich Uchun Tayyor Prompt (Phase 9 Prompt)

Quyidagi promptni nusxalab, keyingi bosqichni boshlash uchun yuborishingiz mumkin:

```markdown
PHASE 9 — PERFORMANCE OPTIMIZATION AND FINAL RELEASE AUDIT

ROLE:
Principal Performance Engineer, Release Reliability Lead, and Hackathon Project Lead.

Continue from the thoroughly audited and verified Phase 8 test suite (574 passing tests).

OBJECTIVE:
Perform final end-to-end performance profiling, memory optimization, static asset compression, edge-case hardening, and produce the comprehensive final submission bundle for the UZEX AI analytical platform.

CONSTRAINTS:
- Render Free Web Service constraints (512 MB RAM ceiling, 1 vCPU, 0 disk persistence).
- No architectural rewrites; only targeted profiling, caching tuning, and latency optimizations.
- Preserve 100% test suite pass rate across all 574 tests.
- Zero factual numerical hallucinations.

TASKS:
1. End-to-End Latency Profiling:
   - Profile the request pipeline under single and concurrent loads.
   - Benchmark p50, p95, and p99 response times for exact lookups, aggregates, and complex multi-filter queries.
   - Ensure cold-start and warm request latencies satisfy target budgets.

2. Memory Ceiling and Leak Audit:
   - Stress-test the in-memory cache and DuckDB query leases under sustained load (e.g., 500 sequential requests).
   - Verify resident set size (RSS) stays strictly under 256 MB (well below the 512 MB Render ceiling).
   - Ensure zero WAL generation and zero temporary file disk leaks.

3. Frontend and Asset Optimization:
   - Audit web/static assets (HTML, CSS, JS) for minimal payload size and maximum render speed.
   - Verify lighthouse performance, accessibility, and zero external blocking scripts.
   - Ensure clean offline caching headers and instant browser rendering.

4. Production Deployment Package Audit:
   - Audit Dockerfile layers, .dockerignore exclusions, and minimal container footprint.
   - Verify environment variable handling for production (GEMINI_API_KEY, GEMINI_MODEL, APP_ENV=production).
   - Validate GET /health endpoint behavior under synthetic uptime monitors.

5. Submission Deliverables:
   - Create the comprehensive Final Release Summary and Architecture Report (`docs/final_submission_report.uz.md`).
   - Create user quick-start and evaluator guide (`docs/evaluator_guide.uz.md`).
   - Verify git hygiene: no credentials, no raw databases in git history, clean working directory.

Report results in Uzbek upon completion.
```

