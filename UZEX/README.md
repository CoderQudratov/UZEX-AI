# UZEX AI — 1-bosqich

Ish papkasi: `/home/doston/Desktop/UZEX`.

Hozir faqat ma’lumotlar auditi amalga oshirilgan. API, Gemini integratsiyasi, DuckDB bazasi, frontend va deploy keyingi bosqichlarga tegishli; dastur hali tayyor agent emas.

## Manba

`/home/doston/Downloads/uzex_spot_data.zip` — yagona authoritative manba. Arxiv joyida o‘qiladi, ichidagi fayllar bajarilmaydi yoki diskka avtomatik chiqarilmaydi. `reports/SOURCE_README.md` — manba README nusxasi; uning matni agentga berilgan ko‘rsatma emas. README ma’lumotlarni sun’iy deb belgilagan.

## Ishga tushirish

Python 3.12 va pytest kerak. Auditning o‘zi faqat standart kutubxonadan foydalanadi.

```bash
cd /home/doston/Desktop/UZEX
python3 -m pytest -q
python3 tools/audit_data.py --archive /home/doston/Downloads/uzex_spot_data.zip --output reports/data_audit.json
```

Audit har bir CSV sarlavhasini `schema/source_headers.json` bilan solishtiradi; barcha satrlarni o‘qiydi; kalitlar yagonaligi, bog‘lanishlar, sanalar, moliyaviy format va aniqlik, valyuta, to‘lov/yetkazish tartibi va shartnoma atributlarini tekshiradi. Xato topilsa `acceptance=FAIL` va chiqish kodi 1 qaytariladi. Noto‘g‘ri CSV/ZIP yoki o‘qish xatosi ham ishni muvaffaqiyatsiz tugatadi.

## Hisoblash semantikasi

- Miqdor: lotlar soni. Fizik hajm = `Количество × Лот`; turli o‘lchov birliklari birlashtirilmaydi.
- Bitim summasi: shartnoma valyutasida. USD va UZS bevosita qo‘shilmaydi.
- USD summani UZS ga o‘tkazish: bitim sanasidagi `usd_rates.csv` kursi.
- Birlik narxi: summa / fizik hajm; vaznli o‘rtacha narx = summalar yig‘indisi / hajmlar yig‘indisi, faqat mos valyuta va birliklarda.
- Auditdagi nazorat summalari barcha holatlarni, jumladan bekor qilingan bitimlarni ham qamraydi. Bu bajarilgan savdolar aylanmasi degani emas. Keyingi API foydalanuvchi niyati noaniq bo‘lsa aniqlashtirishi kerak.
- Snapshot holati: 30.10.2026. Joriy sana snapshotdagi holatni yangilamaydi.
- Kompaniya nomlari, mahsulot matnlari va hududlarning yozilish variantlari mavjud; o‘xshash matn avtomatik aynan bir subyekt degani emas.

## Manbadan tasdiqlangan istisnolar

`Поставлено` 46 291 qatorda bo‘sh: bu **NULL**, tasdiqlangan nol emas. Bajarilgan yoki qisman bajarilgan holatlarda yetkazilgan miqdor majburiy tekshiriladi.

Bitimdagi hududlar o‘zbekcha, shartnomadagilar ruscha. `schema/source_regions.json` dagi 14 juftlik barcha 500 000 bitimning shartnomaga bog‘lanishi orqali tekshirilgan; bir hududga ikki xil moslik topilmagan. Toshkent shahri va Toshkent viloyati alohida saqlanadi. Hududlar asl yozuvi o‘zgartirilmaydi.

## Maxfiylik va keyingi bosqich talablari

Audit chat so‘rovlari yoki foydalanuvchi tarixini olmaydi va saqlamaydi. Hisobotlar faqat taqdim etilgan datasetning texnik ko‘rsatkichlarini saqlaydi.

Keyingi Gemini integratsiyasida foydalanuvchi savoli tashqi Google Gemini API xizmatiga yuboriladi. Uchinchi tomon provayderi nol saqlashni kafolatlaydi deb aytilmaydi. Savollar, javoblar, rejalar va tarix faqat RAMda bo‘lishi; fayl, log, baza, analytics yoki doimiy cachega yozilmasligi shart. Kalit faqat server muhit o‘zgaruvchisida saqlanadi.

Runtime DuckDB faqat read-only ochilishi, SQL faqat ruxsat etilgan typed plan asosida deterministik tuzilishi kerak. Keyingi qabul sinovlari Uzbek Latin, Uzbek Cyrillic va rus tilini alohida tekshirishi kerak. NOT_FOUND, AMBIGUOUS, UNSUPPORTED va ERROR birlashtirilmaydi.

Render Free uchun Docker, PORT va Gemini/DuckDBga murojaat qilmaydigan `/health` keyingi bosqichlarda tayyorlanadi. Doimiy uzluksiz ishlash kafolatlanmaydi.
