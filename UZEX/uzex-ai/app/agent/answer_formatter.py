"""Deterministic plain-text templates. Only result values may appear as facts."""

import json
from datetime import date, time
from decimal import Decimal

from app.agent.query_models import VerifiedResult
from app.db.schema import SCHEMA

MESSAGES = {
    "uz-Latn": {
        "VERIFIED": "Tasdiqlangan natija",
        "NOT_FOUND": "Mos ma’lumot topilmadi.",
        "AMBIGUOUS": "So‘rov noaniq. Aniqlashtirish kerak.",
        "UNSUPPORTED": "Bu so‘rov qo‘llab-quvvatlanmaydi.",
        "ERROR": "So‘rovni bajarib bo‘lmadi. Qayta urinib ko‘ring.",
        "rows": "Qaytarilgan qatorlar",
        "source": "Manba",
        "snapshot": "Holat sanasi",
        "limited": "Natija cheklangan; to‘liq ro‘yxat emas.",
        "unknown": "noma’lum",
        "candidates": "Aniqlashtirish variantlari",
    },
    "uz-Cyrl": {
        "VERIFIED": "Тасдиқланган натижа",
        "NOT_FOUND": "Мос маълумот топилмади.",
        "AMBIGUOUS": "Сўров ноаниқ. Аниқлаштириш керак.",
        "UNSUPPORTED": "Бу сўров қўллаб-қувватланмайди.",
        "ERROR": "Сўровни бажариб бўлмади. Қайта уриниб кўринг.",
        "rows": "Қайтарилган қаторлар",
        "source": "Манба",
        "snapshot": "Ҳолат санаси",
        "limited": "Натижа чекланган; тўлиқ рўйхат эмас.",
        "unknown": "номаълум",
        "candidates": "Аниқлаштириш вариантлари",
    },
    "ru": {
        "VERIFIED": "Подтверждённый результат",
        "NOT_FOUND": "Совпадающие данные не найдены.",
        "AMBIGUOUS": "Запрос неоднозначен. Требуется уточнение.",
        "UNSUPPORTED": "Этот запрос не поддерживается.",
        "ERROR": "Не удалось выполнить запрос. Повторите попытку.",
        "rows": "Возвращено строк",
        "source": "Источник",
        "snapshot": "Состояние на",
        "limited": "Результат ограничен; это не полный список.",
        "unknown": "неизвестно",
        "candidates": "Варианты для уточнения",
    },
}
LABELS = {
    "count": ("Bitimlar soni", "Битимлар сони", "Количество сделок"),
    "delivered_count": (
        "Yetkazilgan bitimlar soni",
        "Етказилган битимлар сони",
        "Сделки с поставкой",
    ),
    "sum_amount": ("Jami summa", "Жами сумма", "Сумма"),
    "avg_amount": (
        "Bitim summasining arifmetik o‘rtachasi",
        "Битим суммасининг арифметик ўртачаси",
        "Средняя сумма сделки",
    ),
    "weighted_unit_price": (
        "Hajm bo‘yicha vaznli birlik narxi",
        "Ҳажм бўйича вазнли бирлик нархи",
        "Средневзвешенная цена единицы",
    ),
}


def format_answer(result: VerifiedResult, language: str) -> str:
    if language not in MESSAGES:
        return (
            "Faqat o‘zbekcha yoki ruscha murojaat qiling. / "
            "Пожалуйста, используйте узбекский или русский язык."
        )
    text = MESSAGES[language]
    lines = [text[result.status]]
    if result.status != "VERIFIED":
        if result.reason in REASONS:
            ru, uz = REASONS[result.reason]
            lines.append(ru if language == "ru" else uz_cyr(uz) if language == "uz-Cyrl" else uz)
        if result.candidates:
            lines.append(text["candidates"] + ":")
            lines.extend(f"{c.label} [{c.value}]" for c in result.candidates)
        return "\n".join(lines)
    index = {"uz-Latn": 0, "uz-Cyrl": 1, "ru": 2}[language]
    lines.append(f"{text['rows']}: {result.row_count}")

    def value(v, field=None):
        if field == "currency":
            return {"Узбекский сум": "UZS", "Доллар США": "USD"}.get(v, str(v))
        if field in ENUM_LABELS and v in ENUM_LABELS[field]:
            return ENUM_LABELS[field][v][index]
        if field == "unit" and v in UNIT_LABELS:
            return UNIT_LABELS[v][index]
        if field == "status" and v in STATUS_LABELS:
            return STATUS_LABELS[v][index]
        if v is None:
            return text["unknown"]
        if isinstance(v, (Decimal, date, time)):
            return str(v)
        # Quoting protects line/control boundaries in officially recorded strings.
        if isinstance(v, str):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    for row in result.rows:
        lines.append(
            "; ".join(
                f"{LABELS.get(k, ('Maydon', 'Майдон', 'Поле'))[index]}: {value(v, k)}"
                for k, v in row.items()
                if k != "period"
            )
        )
    if result.aggregates.get("currency_basis") == "uzs":
        lines.append(
            {
                "uz-Latn": "Summa bitim sanasidagi kurs bilan UZSda.",
                "uz-Cyrl": "Сумма битим санасидаги курс билан UZSда.",
                "ru": "Сумма в UZS по курсу на дату сделки.",
            }[language]
        )
    if result.original_currency:
        prefix = {
            "uz-Latn": "Manba valyutalari: ",
            "uz-Cyrl": "Манба валюталари: ",
            "ru": "Валюты источника: ",
        }[language]
        lines.append(
            prefix
            + " / ".join(
                {"Узбекский сум": "UZS", "Доллар США": "USD"}.get(v, v)
                for v in result.original_currency
            )
        )
    if result.measurement_units:
        lines.append(
            " / ".join(UNIT_LABELS.get(v, (v, v, v))[index] for v in result.measurement_units)
        )
    if result.evidence:
        lines.append(f"{text['source']}: {result.evidence.source}")
        lines.append(f"{text['snapshot']}: {result.evidence.snapshot}")
        if result.evidence.output_limited:
            lines.append(text["limited"])
    return "\n".join(lines)


# Fixed translations of schema labels, not generated facts.
UZ_LABELS = {
    "deal_id": "Bitim raqami",
    "contract_id": "Shartnoma raqami",
    "deal_date": "Bitim sanasi",
    "deal_time": "Bitim vaqti",
    "payment_date": "To‘lov sanasi",
    "delivery_date": "Yetkazish sanasi",
    "seller_inn": "Sotuvchi STIR",
    "buyer_inn": "Xaridor STIR",
    "seller_name": "Sotuvchi nomi",
    "buyer_name": "Xaridor nomi",
    "seller_broker_code": "Sotuvchi broker kodi",
    "buyer_broker_code": "Xaridor broker kodi",
    "seller_broker_name": "Sotuvchi broker nomi",
    "buyer_broker_name": "Xaridor broker nomi",
    "product_name": "Mahsulot nomi",
    "product_description": "Mahsulot tavsifi",
    "tn_ved_code": "TN VED kodi",
    "product_group": "Mahsulot guruhi",
    "product_category": "Mahsulot toifasi",
    "industry": "Sanoat tarmog‘i",
    "brand": "Marka",
    "grade": "Nav",
    "size": "O‘lcham",
    "product_type": "Mahsulot turi",
    "product_class": "Mahsulot sinfi",
    "region": "Hudud",
    "contract_region": "Shartnoma hududi",
    "status": "Bitim holati",
    "contract_type": "Shartnoma turi",
    "contract_form": "Shartnoma shakli",
    "auction_type": "Savdo turi",
    "currency": "Valyuta",
    "unit": "O‘lchov birligi",
    "quantity": "Lotlar soni",
    "lot_size": "Lot hajmi",
    "amount": "Bitim summasi",
    "amount_uzs": "Bitim summasi UZS",
    "starting_price": "Boshlang‘ich narx",
    "delivered_lots": "Yetkazilgan lotlar",
    "volume": "Fizik hajm",
    "delivered_volume": "Yetkazilgan hajm",
    "unit_price_rounded_8": "Birlik narxi (8 kasr xonasi)",
    "registered_date": "Ro‘yxatdan o‘tgan sana",
    "valid_until": "Amal qilish tugashi",
    "warehouse_address": "Ombor manzili",
    "base_price": "Bazis narxi",
    "min_amount": "Eng kichik bitim summasi",
    "max_amount": "Eng katta bitim summasi",
    "sum_volume": "Jami fizik hajm",
    "sum_delivered_volume": "Jami ma’lum yetkazilgan hajm",
    "sum_lots": "Jami lotlar",
    "sum_delivered_lots": "Jami ma’lum yetkazilgan lotlar",
    "min_unit_price": "Eng kichik birlik narxi (8 kasr xonasi)",
    "max_unit_price": "Eng katta birlik narxi (8 kasr xonasi)",
    "month": "Oy",
    "period": "Davr indeksi",
    "period_start": "Davr boshlanishi",
    "period_end": "Davr oxiri",
    "inn": "STIR",
    "name": "Nom",
    "activity": "Faoliyat",
    "role": "Rol",
    "vat_payer": "QQS to‘lovchi",
    "broker_code": "Broker kodi",
    "deposit_percent": "Garov foizi",
    "delivery_basis": "Yetkazish bazisi",
    "packaging": "Qadoqlash",
    "payment_days": "To‘lov muddati kun",
    "delivery_days": "Yetkazish muddati kun",
}


def uz_cyr(text):
    pairs = {
        "sh": "ш",
        "ch": "ч",
        "yo": "ё",
        "yu": "ю",
        "ya": "я",
        "o‘": "ў",
        "g‘": "ғ",
        "a’": "аъ",
    }
    single = dict(zip("abvgdezijyklmnoprstufxqh", "абвгдезижйклмнопрстуфхқҳ", strict=True))
    result = ""
    index = 0
    while index < len(text):
        pair = text[index : index + 2].lower()
        if pair in pairs:
            char = pairs[pair]
            step = 2
        else:
            char = single.get(text[index].lower(), text[index])
            step = 1
        result += char.upper() if text[index].isupper() else char
        index += step
    return result


RUS_LABELS = {c.name: c.source for columns in SCHEMA.values() for c in columns}
RUS_LABELS.update(
    {
        "seller_name": "Продавец",
        "buyer_name": "Покупатель",
        "seller_broker_name": "Брокер продавца",
        "buyer_broker_name": "Брокер покупателя",
        "product_name": "Продукт",
        "contract_region": "Регион контракта",
        "amount_uzs": "Сумма в UZS",
        "volume": "Объём",
        "delivered_volume": "Поставленный объём",
        "unit_price_rounded_8": "Цена единицы (8 знаков)",
        "min_amount": "Минимальная сумма сделки",
        "max_amount": "Максимальная сумма сделки",
        "sum_volume": "Общий объём",
        "sum_delivered_volume": "Известный поставленный объём",
        "sum_lots": "Всего лотов",
        "sum_delivered_lots": "Известные поставленные лоты",
        "min_unit_price": "Минимальная цена единицы",
        "max_unit_price": "Максимальная цена единицы",
        "month": "Месяц",
        "period": "Индекс периода",
        "period_start": "Начало периода",
        "period_end": "Конец периода",
    }
)
for key, uz in UZ_LABELS.items():
    LABELS.setdefault(key, (uz, uz_cyr(uz), RUS_LABELS.get(key, "Поле")))

REASONS = {
    "MIXED_CURRENCIES": (
        "Разделите валюты или явно выберите пересчёт в UZS.",
        "Valyutalarni ajrating yoki UZSga aylantirishni belgilang.",
    ),
    "CURRENCY_INTERPRETATION": (
        "Укажите исходную валюту или пересчёт в UZS.",
        "Asl valyuta yoki UZSga aylantirishni belgilang.",
    ),
    "MIXED_UNITS": ("Разделите разные единицы измерения.", "Turli olchov birliklarini ajrating."),
    "PRICE_AVERAGE_MEANING": (
        "Уточните: средняя сумма сделки или взвешенная цена единицы.",
        "Bitim summasi ortachasi yoki hajm boyicha vaznli birlik narxini belgilang.",
    ),
    "CONTRACT_STATUS_ABSENT": (
        "В источнике нет отдельного статуса контракта.",
        "Manbada shartnomaning alohida holati mavjud emas.",
    ),
    "LOT_MEANING": (
        "Размеры лотов или единицы различаются.",
        "Lot hajmlari yoki olchov birliklari farq qiladi.",
    ),
}

UNIT_LABELS = {
    "килограмм": ("kilogramm", "килограмм", "килограмм"),
    "тонна": ("tonna", "тонна", "тонна"),
    "литр": ("litr", "литр", "литр"),
    "метр": ("metr", "метр", "метр"),
    "кв.метр": ("kvadrat metr", "квадрат метр", "кв.метр"),
    "куб.метр": ("kub metr", "куб метр", "куб.метр"),
    "штука": ("dona", "дона", "штука"),
}
STATUS_LABELS = {
    "Новый": ("Yangi", "Янги", "Новый"),
    "Не подписан": ("Imzolanmagan", "Имзоланмаган", "Не подписан"),
    "Заключен": ("Tuzilgan", "Тузилган", "Заключен"),
    "Ждёт оплату": ("To‘lovni kutmoqda", "Тўловни кутмоқда", "Ждёт оплату"),
    "Оплачен": ("To‘langan", "Тўланган", "Оплачен"),
    "Исполнен": ("Bajarilgan", "Бажарилган", "Исполнен"),
    "Исполнен(Частично)": ("Qisman bajarilgan", "Қисман бажарилган", "Исполнен(Частично)"),
    "Аннулирован(Не оплачен)": (
        "Bekor qilingan (to‘lanmagan)",
        "Бекор қилинган (тўланмаган)",
        "Аннулирован(Не оплачен)",
    ),
}

ENUM_LABELS = {
    "contract_type": {
        "Внутренний": ("Ichki", "Ички", "Внутренний"),
        "Экспортный": ("Eksport", "Экспорт", "Экспортный"),
    },
    "contract_form": {
        "Спот": ("Spot", "Спот", "Спот"),
        "Форвард": ("Forvard", "Форвард", "Форвард"),
        "Фьючерс": ("Fyuchers", "Фьючерс", "Фьючерс"),
    },
    "auction_type": {
        "Английский аукцион": ("Ingliz auksioni", "Инглиз аукциони", "Английский аукцион"),
        "Обратный аукцион": ("Teskari auksion", "Тескари аукцион", "Обратный аукцион"),
        "Двусторонний аукцион": (
            "Ikki tomonlama auksion",
            "Икки томонлама аукцион",
            "Двусторонний аукцион",
        ),
    },
    "role": {
        "Продавец": ("Sotuvchi", "Сотувчи", "Продавец"),
        "Покупатель": ("Xaridor", "Харидор", "Покупатель"),
    },
    "vat_payer": {"Да": ("Ha", "Ҳа", "Да"), "Нет": ("Yoq", "Йўқ", "Нет")},
}
