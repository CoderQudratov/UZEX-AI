# 1-bosqich hisoboti — 2026-11-05 (Asia/Tashkent)

## 1. Bajarilgan ish

Ish `/home/doston/Desktop/UZEX` papkasida bajarildi. Manba README va to‘qqizta CSV o‘qildi. Arxivdagi matnlar ko‘rsatma sifatida bajarilmadi. Arxiv SHA-256: `88182bf4dad3569eea5fac611e8a16db7a455110fdaa6495650e7d87e09ac258`.

To‘liq audit: **PASS**. 500 000 noyob bitim; 6 616 shartnoma; 14 392 ishtirokchi; 120 broker; 1 765 kunlik kurs. Bitimlar: 2022-01-03 — 2026-10-30. Har bir bitimning shartnoma, ishtirokchi, broker va kurs bog‘lanishi tekshirildi. Dastur qamrab olgan tekshiruvlarda yakuniy xato yoki ogohlantirish yo‘q; bu kelajakdagi barcha savollarga javob berish aniqligi isbotlanganini anglatmaydi.

493 410 bitim UZS, 6 590 bitim USD valyutasida. Manba summalari va narxlari ko‘pi bilan 2 kasr xonasiga ega; valyuta ko‘paytmasi 4 kasr xonasini talab qiladi. Hisoblashda float ishlatilmagan.

46 291 ta `Поставлено` qiymati bo‘sh: keyingi bazada NULL saqlanishi kerak. 14 ta hudud mosligi barcha bitim-shartnoma bog‘lanishlarida bir qiymatli tasdiqlandi. Asl yozuvlar saqlanadi.

## 2. Yaratilgan fayllar

- `tools/audit_data.py`: faqat o‘qiydigan, xatoda muvaffaqiyatsiz tugaydigan offline audit.
- `tests/test_audit.py`: Decimal, sana, ZIP xavfsizligi, NULL va hudud regressiya testlari.
- `schema/source_headers.json`: haqiqiy CSV sarlavhalari.
- `schema/source_regions.json`: dataset bog‘lanishlaridan olingan 14 hudud juftligi.
- `reports/data_audit.json`: to‘liq mashina o‘qiydigan natija.
- `reports/SOURCE_README.md`: manba README nusxasi.
- `README.md`, `pyproject.toml`, `.gitignore`, ushbu hisobot.

## 3. Haqiqatan bajarilgan asosiy buyruqlar

Ish papkasi: `/home/doston/Desktop/UZEX`.

```bash
python3 -m pytest -q
python3 tools/audit_data.py --archive /home/doston/Downloads/uzex_spot_data.zip --output reports/data_audit.json
python3 -m compileall -q tools tests
```

Qo‘shimcha bajarilgan tekshiruvlar: `pwd`, `rg --files`, `ls -ld`, Python orqali ZIP a’zolari/README/CSV sarlavhalari va namunalarini o‘qish, barcha hudud juftliklari va bo‘sh yetkazish qiymatlarini sanash, yakuniy hisobot yig‘indilarini `assert` bilan solishtirish. Dastlabki 6000 baytlik namuna o‘qish UTF-8 belgisi o‘rtasida to‘xtab xato berdi; keyin `TextIOWrapper` orqali to‘liq CSV satrlarini o‘qish qo‘llandi.

## 4. Testlar va tuzatishlar

Dastlab 26 unit test o‘tdi. Birinchi to‘liq audit **FAIL**, 46.458 s: hududlar matnini bevosita tenglashtirish hamda bo‘sh yetkazish sonini majburiy son deb tekshirish noto‘g‘ri edi. Ma’lumotlar o‘zgartirilmadi. Manbadan sabablar tekshirildi va ikkita regressiya testi oldin muvaffaqiyatsiz ishga tushirildi (26 PASS / 2 FAIL), so‘ng NULL semantikasi va qat’iy hudud mosligi bilan tuzatildi.

Yakun: **28 PASS, 0 FAIL** (pytest: 0.03 s). To‘liq audit: **PASS**, chiqish kodi 0. Compile tekshiruvi ham chiqish kodi 0. Hisobotdagi valyuta va holat sonlari jami 500 000 ekanligi mustaqil assert bilan tekshirildi.

## 5. Qolgan aniqlik va xavfsizlik xatarlari

- Ma’lumotlar README bo‘yicha sun’iy; real birja faktlari sifatida taqdim etilmasin.
- Mahsulot va kompaniya yozuvlarining turli variantlari avtomatik birlashtirilmasin; noaniq nomlar aniqlashtirilsin.
- Bekor qilingan bitimlar, valyuta, o‘lchov birligi va snapshot sanasi keyingi javoblarda ochiq ko‘rsatilishi kerak.
- Bu bosqich faqat offline audit. DuckDB, Gemini, FastAPI, uch til/yozuv yo‘nalishi, so‘rov cheklovlari, maxfiylik nazorati va Render deploy hali amalga oshirilmagan yoki sinovdan o‘tmagan.
- Foydalanuvchi savollari keyinchalik Gemini xizmatiga yuboriladi; provayder nol saqlash kafolati bor deb aytilmaydi. Savol/javob/reja/tarix persistent saqlanmasin.

## 6. Haqiqiy tezlik o‘lchovi

Yakuniy barcha CSV auditi: **47.866 s**; SHA-256 va barcha satrlar tekshiruvi bilan birga. Bu offline build tekshiruvi, API javob tezligi emas. p50/p95 hali o‘lchanmadi: ishlaydigan API ushbu bosqich doirasida yo‘q.

## 7. Keyingi bosqich uchun tayyor prompt

> 2-bosqichni `/home/doston/Desktop/UZEX` da bajaring: avval README va 1-bosqich hisobotini o‘qing. Tasdiqlangan CSV sxemalariga tayangan holda Python 3.12 va DuckDB bilan build vaqtidagi deterministik importni yarating. Identifikatorlarni matn, sanalarni DATE, moliyaviy qiymatlarni yetarli DECIMAL aniqligida, bo‘sh yetkazish qiymatlarini NULL saqlang. Asl hudud nomlarini saqlab, tasdiqlangan mosliklarni alohida qo‘llang. Runtime uchun faqat read-only ulanish qatlamini yarating; runtime yozuvlarini taqiqlang. 500 000 yozuv, kalitlar/bog‘lanishlar, Decimal nazorat summalari, valyuta konversiyasi, NULL va read-only taqiqini haqiqiy testlar bilan tekshiring. Build vaqtini va fayl hajmini o‘lchang. Ushbu bosqichda Gemini/API/frontend/deployga o‘tmang. Yakunda yetti bandli o‘zbekcha hisobot bering.
