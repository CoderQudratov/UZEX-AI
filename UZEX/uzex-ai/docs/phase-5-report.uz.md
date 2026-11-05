# Phase 5 — FastAPI Backend Integration

Sana: 2026-11-05, Asia/Tashkent.  
Loyiha: `/home/doston/Desktop/UZEX/uzex-ai`.  
Holat: **PASS**. Frontend hali yaratilmadi (Phase 6 ga qoldirildi).  

---

## 1. Bajarilgan ishlar

Production-ready, past kechikishli (low-latency) va xavfsiz FastAPI xizmati yaratildi:

1. **`GET /health`**:
   - Tizim tayyorligini darhol tekshiradi (HTTP 200 `{"status": "ok"}`).
   - Hech qanday DuckDB so‘rovi bajarmaydi.
   - Hech qanday Gemini/tashqi API chaqiruvini amalga oshirmaydi.
   - Diskka hech narsa yozmaydi va log chiqarmaydi.

2. **`GET /api/v1/status`**:
   - Backend holati, muhit (`app_env`), tasdiqlangan ma’lumotlar bazasi versiyasi (`dataset_version`), model nomi va DuckDB ombori tayyorligini qaytaradi.
   - API kalitlari yoki ichki fayl yo‘llarini mutlaqo oshkor qilmaydi.

3. **`POST /api/v1/chat`**:
   - Kiruvchi so‘rov uzunligi va formatini tekshiradi (bo‘sh bo‘lsa `AMBIGUOUS`, 4096 baytdan oshsa `UNSUPPORTED`).
   - Qo‘llab-quvvatlanmaydigan tillarni darhol xavfsiz filtrlaydi (`UNSUPPORTED / UNSUPPORTED_LANGUAGE`).
   - Bounded, faqat RAMda yashovchi LRU kesh (`ChatCache`) orqali takroriy tasdiqlangan javoblarni < 1 ms ichida qaytaradi.
   - Aniq identifikatorli so‘rovlarni (`bitim 100001`, `STIR ...`, `broker ...`) Gemini chaqiruvisiz to‘g‘ridan-to‘g‘ri deterministik SQL ga yo‘naltiradi.
   - Murakkab so‘rovlarni Gemini semantik rejalashtiruvchisi, semantik qorovul (`check_decision`) va tekshirilgan Pydantic `QueryPlan` orqali qayta ishlaydi.
   - Read-only DuckDB omborida xavfsiz parametrli SQL orqali bajaradi.
   - Natijani asl foydalanuvchi tili va yozuvida (`uz/latin`, `uz/cyrillic`, `ru/cyrillic`) deterministik shablonlar bilan formatlaydi.
   - Strukturaviy `evidence` (dataset_version, tables, filters, source_count) va `latency_ms` bilan qaytaradi.

4. **`POST /api/v1/chat/stream`** (Ixtiyoriy SSE oqimi):
   - Server-Sent Events (`text/event-stream`) protokoli orqali oraliq status (`PROCESSING`) va yakuniy javobni xavfsiz uzatadi.

---

## 2. Xavfsizlik va resurslarni boshqarish

- **Request size limit**: 64 KB dan katta HTTP payloadlar 413 Payload Too Large xatosi bilan to‘xtatiladi.
- **Concurrency semaphore**: Bounded `asyncio.Semaphore` va `ReadOnlyWarehouse` semafori bir vaqtning o‘zida qabul qilinadigan so‘rovlar sonini qat’iy nazorat qiladi.
- **Read-only xavfsiz DuckDB**: Baza faqat read-only rejimida ochiladi, hech qanday xom SQL, DROP, UPDATE yoki foydalanuvchi yo‘llari bajarilmaydi.
- **Maxfiylik va Zero User Persistence**: Chat so‘rovlari, javoblari, foydalanuvchi tarixi diskka, doimiy loglarga yoki tashqi tahlil tizimlariga aslo yozilmaydi.
- **Xatolarni yashirish**: Stack trace, ichki istisnolar yoki SQL kodlari mijozga ko‘rsatilmaydi; faqat xavfsiz standart xato konverti (`ErrorEnvelope`) beriladi.
- **CORS**: Faqat tasdiqlangan lokal hostlar uchun cheklangan, ochiq yovvoyi (`*`) ruxsatnomalarsiz sozlangan.

---

## 3. Yaratilgan va o‘zgartirilgan fayllar

- `app/services/cache.py` — RAM-only bounded LRU kesh (256 element).
- `app/services/chat_models.py` — `ChatRequest`, `ChatEvidence`, `ChatResponse` Pydantic v2 qat’iy modellari.
- `app/services/chat_service.py` — So‘rov quvuri, orkestratsiya, kesh va dalillarni birlashtiruvchi servis.
- `app/services/__init__.py` — Servis eksportlari.
- `app/api/application.py` — `/health`, `/api/v1/status`, `/api/v1/chat`, `/api/v1/chat/stream` marshrutlari, CORS, o‘lcham chegaralari va xavfsiz lifespan.
- `tests/integration/test_api_v1.py` — 18 ta integratsiya va xavfsizlik testlari.
- `docs/phase-5-report.uz.md` — Ushbu hisobot.

---

## 4. Test natijalari (16 ta talab qilingan qabul sinovi)

| № | Test holati | Natija | Tafsilot |
|---|---|---|---|
| 1 | Valid Uzbek Latin request | **PASS** | `bitim 100001` → status: VERIFIED, lang: uz, script: latin, source_count: 1 |
| 2 | Valid Uzbek Cyrillic request | **PASS** | `битим 100001` → status: VERIFIED, lang: uz, script: cyrillic, source_count: 1 |
| 3 | Valid Russian request | **PASS** | `сделка 100001` → status: VERIFIED, lang: ru, script: cyrillic, source_count: 1 |
| 4 | Unsupported language | **PASS** | Ingliz/fransuz/turk tillari → status: UNSUPPORTED, evidence: None |
| 5 | Invalid JSON | **PASS** | Noto‘g‘ri sintaksis → HTTP 422, INVALID_REQUEST |
| 6 | Oversized payload | **PASS** | >4096 belgili matn va >64KB body → 422 va 413 INVALID_REQUEST |
| 7 | Missing message | **PASS** | Bo‘sh `{}` yoki noto‘g‘ri kalitlar → HTTP 422, INVALID_REQUEST |
| 8 | Gemini timeout | **PASS** | Model kechikishi → status: ERROR, xavfsiz xabar, stack trace yo‘q |
| 9 | Invalid Gemini output | **PASS** | Buzilgan JSON qaytsa → status: ERROR, xavfsiz xabar |
| 10 | Database timeout | **PASS** | DuckDB timeout bersa → status: ERROR, ichki SQL oshkor etilmaydi |
| 11 | Ambiguous query | **PASS** | Noaniq so‘rov → status: AMBIGUOUS, aniqlashtirish talab etiladi |
| 12 | Unknown STIR | **PASS** | Mavjud bo‘lmagan STIR → status: NOT_FOUND, source_count: 0 |
| 13 | Injection attempts | **PASS** | SQL/Prompt injection → xavfsiz to‘xtatiladi, baza butun |
| 14 | Concurrent requests | **PASS** | 12 ta parallel so‘rov muvaffaqiyatli, poyga holati yo‘q |
| 15 | /health DB/Geminisiz | **PASS** | Baza va Gemini chaqirilmasdan tezkor HTTP 200 beradi |
| 16 | No persistent writes | **PASS** | Diskka hech qanday foydalanuvchi ma’lumoti yozilmadi |
| + | `/api/v1/status` | **PASS** | Backend va warehouse holatini xavfsiz tasdiqlaydi |
| + | `/api/v1/chat/stream` | **PASS** | SSE orqali `data: {...}` oqimi to‘g‘ri ishlaydi |

**Umumiy loyiha testlari: 326 ta PASS, 0 ta FAIL.**  
Ruff lint va format: **All checks passed!**

