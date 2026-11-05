"""Fixed, authored language/intent oracles; never derive expectations from production NLP.

These fixtures test offline contracts/guards. Feeding their canned outputs into a fake
planner is NOT a measurement of Gemini semantic accuracy. Live evaluation is separate.
"""

from dataclasses import dataclass
from datetime import date

from app.agent.query_models import Filter, Lookup, Order, QueryPlan
from app.agent.semantic_models import LANGUAGE_MAP


@dataclass(frozen=True)
class Case:
    text: str
    language: str
    expected: str  # fixed intent tag or semantic status/reason


# Each row was authored with its intent explicitly selected. No production rule labels it.
ROWS = [
    ("2025 yilda nechta bitim bor?", "uz_latn", "count_2025"),
    ("2025 yil bitimlar soni", "uz_latn", "count_2025"),
    ("bitimlar nechta, 2025 yilda?", "uz_latn", "count_2025"),
    ("manga 2025 yilgi bitimlar sonini korsat", "uz_latn", "count_2025"),
    ("mn 2025 yilda nechta bitim bolganini bilmoqchiman", "uz_latn", "count_2025"),
    ("2025 da bitimlar soni kerak", "uz_latn", "count_2025"),
    ("2025 йилда нечта битим бор?", "uz_cyrl", "count_2025"),
    ("Битимлар сони 2025 йилда", "uz_cyrl", "count_2025"),
    ("Менга 2025 йилги битимлар сонини кўрсат", "uz_cyrl", "count_2025"),
    ("2025 да битимлар нечта?", "uz_cyrl", "count_2025"),
    ("Сколько сделок в 2025 году?", "ru", "count_2025"),
    ("Количество сделок за 2025 год", "ru", "count_2025"),
    ("Покажи количество сделок за 2025 год", "ru", "count_2025"),
    ("За 2025 год сколько сделок?", "ru", "count_2025"),
    ("Сделок в 2025 году сколько?", "ru", "count_2025"),
    ("2025 dan oldin nechta bitim?", "uz_latn", "before_2025"),
    ("nechta bitim 2025 dan oldin bolgan?", "uz_latn", "before_2025"),
    ("2025 дан олдин нечта битим?", "uz_cyrl", "before_2025"),
    ("Битимлар сони 2025 дан олдин", "uz_cyrl", "before_2025"),
    ("Сколько сделок до 2025 года?", "ru", "before_2025"),
    ("До 2025 года количество сделок", "ru", "before_2025"),
    ("2025 dan keyin nechta bitim?", "uz_latn", "after_2025"),
    ("bitimlar soni 2025 dan keyin", "uz_latn", "after_2025"),
    ("2025 дан кейин нечта битим?", "uz_cyrl", "after_2025"),
    ("Битимлар сони 2025 дан кейин", "uz_cyrl", "after_2025"),
    ("Сколько сделок после 2025 года?", "ru", "after_2025"),
    ("После 2025 года количество сделок", "ru", "after_2025"),
    ("barcha bitimlar soni", "uz_latn", "all_count"),
    ("hamma bitimlar nechta?", "uz_latn", "all_count"),
    ("Барча битимлар сони", "uz_cyrl", "all_count"),
    ("Барча битимлар нечта?", "uz_cyrl", "all_count"),
    ("Сколько всего сделок?", "ru", "all_count"),
    ("Количество всех сделок", "ru", "all_count"),
    ("faqat bajarilgan bitimlar soni", "uz_latn", "done"),
    ("bajarilgan bitimlar nechta?", "uz_latn", "done"),
    ("Фақат бажарилган битимлар сони", "uz_cyrl", "done"),
    ("Бажарилган битимлар нечта?", "uz_cyrl", "done"),
    ("Сколько только исполненных сделок?", "ru", "done"),
    ("Количество исполненных сделок", "ru", "done"),
    ("bajarilgan bitimlar kerak emas, qolgan bitimlar soni", "uz_latn", "exclude_done"),
    ("bajarilgan bitimlarni chiqarma, bitimlar soni kerak", "uz_latn", "exclude_done"),
    ("Бажарилган битимлар керак эмас, қолган битимлар сони", "uz_cyrl", "exclude_done"),
    ("Исключи исполненные сделки, покажи количество", "ru", "exclude_done"),
    ("Исполненные сделки не нужны, сколько осталось сделок?", "ru", "exclude_done"),
    ("bekor qilingan bitimlar soni", "uz_latn", "cancelled"),
    ("bekor qilingan bitimlar nechta?", "uz_latn", "cancelled"),
    ("Бекор қилинган битимлар сони", "uz_cyrl", "cancelled"),
    ("Сколько отмененных сделок?", "ru", "cancelled"),
    ("Количество аннулированных сделок", "ru", "cancelled"),
    ("qisman bajarilgan bitimlar soni", "uz_latn", "partial"),
    ("qisman bajarilgan bitimlar nechta?", "uz_latn", "partial"),
    ("Қисман бажарилган битимлар сони", "uz_cyrl", "partial"),
    ("Количество частично исполненных сделок", "ru", "partial"),
    ("Сколько частично исполненных сделок?", "ru", "partial"),
    ("2025 yilda tonnada eng kop sement olgan firma", "uz_latn", "buyer_tonnes_2025"),
    ("sementni 2025 da tonnada eng kop qaysi firma olgan", "uz_latn", "buyer_tonnes_2025"),
    ("2025 yilda sementni tonnada eng kop sotib olgan firma", "uz_latn", "buyer_tonnes_2025"),
    ("2025 да цементни тоннада энг кўп олган фирма", "uz_cyrl", "buyer_tonnes_2025"),
    ("2025 йилда тоннада энг кўп цемент сотиб олган фирма", "uz_cyrl", "buyer_tonnes_2025"),
    ("Какая компания купила больше всего цемента в тоннах в 2025 году?", "ru", "buyer_tonnes_2025"),
    ("Купила больше всего цемента в тоннах какая компания за 2025 год?", "ru", "buyer_tonnes_2025"),
    ("2025 yilda tonnada eng kop sement sotgan firma", "uz_latn", "seller_tonnes_2025"),
    ("sementni tonnada 2025 da eng kop qaysi firma sotgan", "uz_latn", "seller_tonnes_2025"),
    ("2025 да тоннада энг кўп цемент сотган фирма", "uz_cyrl", "seller_tonnes_2025"),
    (
        "Какая компания продала больше всего цемента в тоннах в 2025 году?",
        "ru",
        "seller_tonnes_2025",
    ),
    (
        "Продала больше всего цемента в тоннах какая компания в 2025 году?",
        "ru",
        "seller_tonnes_2025",
    ),
    ("2025 yildagi bitimlar summasi UZSda jami qancha?", "uz_latn", "sum_uzs_2025"),
    ("2025 da bitimlar jami summasini UZSga aylantir", "uz_latn", "sum_uzs_2025"),
    ("2025 йилдаги битимлар суммаси UZSда қанча?", "uz_cyrl", "sum_uzs_2025"),
    ("Общая сумма сделок за 2025 год в UZS", "ru", "sum_uzs_2025"),
    ("Сумму сделок за 2025 год пересчитай в UZS", "ru", "sum_uzs_2025"),
    ("2025 yilda faqat USD bitimlari jami summasi asl USDda", "uz_latn", "sum_usd_2025"),
    ("2025 йилда фақат USD битимлари жами суммаси асл USDда", "uz_cyrl", "sum_usd_2025"),
    ("Сумма только долларовых сделок за 2025 год в исходной валюте USD", "ru", "sum_usd_2025"),
    ("2025 yilda bitim summasining arifmetik ortachasi UZSda", "uz_latn", "avg_uzs_2025"),
    ("2025 йилда битим суммасининг арифметик ўртачаси UZSда", "uz_cyrl", "avg_uzs_2025"),
    ("Средняя арифметическая сумма сделки за 2025 год в UZS", "ru", "avg_uzs_2025"),
    ("bitim 100001", "uz_latn", "lookup_tx"),
    ("битим 100001", "uz_cyrl", "lookup_tx"),
    ("сделка 100001", "ru", "lookup_tx"),
    ("shartnoma 100001", "uz_latn", "lookup_contract"),
    ("шартнома 100001", "uz_cyrl", "lookup_contract"),
    ("контракт 100001", "ru", "lookup_contract"),
    ("STIR 915688255", "uz_latn", "lookup_stir"),
    ("СТИР 915688255 ҳақида", "uz_cyrl", "lookup_stir"),
    ("ИНН 915688255", "ru", "lookup_stir"),
    ("broker BK001", "uz_latn", "lookup_broker"),
    ("брокер BK001 ҳақида", "uz_cyrl", "lookup_broker"),
    ("Покажи брокера BK001", "ru", "lookup_broker"),
    ("2025 yilda eng kop sement olgan firma", "uz_latn", "AMBIGUOUS:METRIC_AMBIGUOUS"),
    ("sementni 2025 da eng kop qaysi firma olgan", "uz_latn", "AMBIGUOUS:METRIC_AMBIGUOUS"),
    ("2025 да цементни энг кўп олган фирма", "uz_cyrl", "AMBIGUOUS:METRIC_AMBIGUOUS"),
    ("Какая компания купила больше всего цемента в 2025 году?", "ru", "AMBIGUOUS:METRIC_AMBIGUOUS"),
    ("qanca summa kerak, eng kop firma", "uz_latn", "AMBIGUOUS:CURRENCY_AMBIGUOUS"),
    ("eng katta summa bitimini korsat", "uz_latn", "AMBIGUOUS:CURRENCY_AMBIGUOUS"),
    ("Самая большая сумма сделки", "ru", "AMBIGUOUS:CURRENCY_AMBIGUOUS"),
    ("kerak", "uz_latn", "AMBIGUOUS:MISSING_TASK"),
    ("kerak emas", "uz_latn", "AMBIGUOUS:NEGATION_TARGET"),
    ("kkmas", "uz_latn", "AMBIGUOUS:NEGATION_TARGET"),
    ("kerak emasmi", "uz_latn", "AMBIGUOUS:NEGATION_QUESTION"),
    ("kerak emas demadim", "uz_latn", "AMBIGUOUS:DOUBLE_NEGATION"),
    ("керак", "uz_cyrl", "AMBIGUOUS:MISSING_TASK"),
    ("керак эмас", "uz_cyrl", "AMBIGUOUS:NEGATION_TARGET"),
    ("керак эмасми", "uz_cyrl", "AMBIGUOUS:NEGATION_QUESTION"),
    ("керак эмас демадим", "uz_cyrl", "AMBIGUOUS:DOUBLE_NEGATION"),
    ("shularni ham korsat", "uz_latn", "AMBIGUOUS:FOLLOWUP_UNRESOLVED"),
    ("ularni sotib olgan firma", "uz_latn", "AMBIGUOUS:FOLLOWUP_UNRESOLVED"),
    ("шу битимларни ҳам кўрсат", "uz_cyrl", "AMBIGUOUS:FOLLOWUP_UNRESOLVED"),
    ("Покажи эти сделки", "ru", "AMBIGUOUS:FOLLOWUP_UNRESOLVED"),
    ("Какой из предыдущих покупателей?", "ru", "AMBIGUOUS:FOLLOWUP_UNRESOLVED"),
    (
        "2025 yilda shartnoma statusi faol bolganlar nechta?",
        "uz_latn",
        "UNSUPPORTED:UNSUPPORTED_SCHEMA",
    ),
    ("Шартнома статуси бўйича маълумот", "uz_cyrl", "UNSUPPORTED:UNSUPPORTED_SCHEMA"),
    ("Статус контракта активный", "ru", "UNSUPPORTED:UNSUPPORTED_SCHEMA"),
    (
        "agar foyda yaxshi bolsa aksiyalarni sotib ol",
        "uz_latn",
        "UNSUPPORTED:UNSUPPORTED_CONDITION",
    ),
    ("Агар фойда яхши бўлса, акцияларни сотиб ол", "uz_cyrl", "UNSUPPORTED:UNSUPPORTED_CONDITION"),
    ("Если прогноз хороший, купи акции", "ru", "UNSUPPORTED:UNSUPPORTED_CONDITION"),
    ("menga ob havo haqida ayt", "uz_latn", "UNSUPPORTED:OUT_OF_SCOPE"),
    ("Менга об ҳаво ҳақида айт", "uz_cyrl", "UNSUPPORTED:OUT_OF_SCOPE"),
    ("Какая погода завтра?", "ru", "UNSUPPORTED:OUT_OF_SCOPE"),
    ("How many transactions in 2025?", "unsupported", "UNSUPPORTED:UNSUPPORTED_LANGUAGE"),
    ("Show the biggest buyer", "unsupported", "UNSUPPORTED:UNSUPPORTED_LANGUAGE"),
    ("What is the total transaction amount?", "unsupported", "UNSUPPORTED:UNSUPPORTED_LANGUAGE"),
    ("Combien de transactions en 2025?", "unsupported", "UNSUPPORTED:UNSUPPORTED_LANGUAGE"),
    ("Hola, cuantas transacciones hay?", "unsupported", "UNSUPPORTED:UNSUPPORTED_LANGUAGE"),
    ("Kaç işlem var?", "unsupported", "UNSUPPORTED:UNSUPPORTED_LANGUAGE"),
    ("Wie viele Transaktionen gibt es?", "unsupported", "UNSUPPORTED:UNSUPPORTED_LANGUAGE"),
    ("كم عدد المعاملات؟", "unsupported", "UNSUPPORTED:UNSUPPORTED_LANGUAGE"),
    ("有多少笔交易？", "unsupported", "UNSUPPORTED:UNSUPPORTED_LANGUAGE"),
    ("2025 yilda сумма bitimlar soni emas, jami summa UZSda kerak", "uz_latn", "sum_uzs_2025"),
    ("2025 йилда сумма битимлар сони эмас, жами сумма UZSда керак", "uz_cyrl", "sum_uzs_2025"),
    ("miqdor emas, 2025 bitimlar summasi UZSda", "uz_latn", "sum_uzs_2025"),
    ("2025 yildagi TN VED 252329 bitimlar soni", "uz_latn", "code_count_2025"),
    ("2025 йилдаги ТН ВЭД 252329 битимлар сони", "uz_cyrl", "code_count_2025"),
    ("Количество сделок по ТН ВЭД 252329 за 2025 год", "ru", "code_count_2025"),
    ("manga 2025 da nechta bitim?", "uz_latn", "count_2025"),
    ("2025 yilda mn bitimlar sonini sorayapman", "uz_latn", "count_2025"),
    ('menga "MN MANGA KOP" kompaniyasi haqida ayt', "uz_latn", "AMBIGUOUS:ENTITY_AMBIGUOUS"),
    ('Сколько сделок у компании "Қўқон"?', "ru", "AMBIGUOUS:ENTITY_AMBIGUOUS"),
]
CASES = tuple(Case(*row) for row in ROWS)


def expected_plan(case):
    """Hand-selected intent tags map to fixed structured plans, never inspect utterance text."""
    tag = case.expected
    if ":" in tag:
        return None
    language = LANGUAGE_MAP[case.language]
    filters = []
    if tag.endswith("_2025"):
        filters.append(
            Filter(field="deal_date", op="between", values=(date(2025, 1, 1), date(2025, 12, 31)))
        )
    if tag in ("count_2025", "all_count", "before_2025", "after_2025"):
        if tag == "before_2025":
            filters = [Filter(field="deal_date", op="lt", values=(date(2025, 1, 1),))]
        if tag == "after_2025":
            filters = [Filter(field="deal_date", op="gte", values=(date(2026, 1, 1),))]
        return QueryPlan(
            kind="aggregate", language=language, metrics=("count",), filters=tuple(filters)
        )
    statuses = {
        "done": ("eq", "Исполнен"),
        "exclude_done": ("ne", "Исполнен"),
        "cancelled": ("eq", "Аннулирован(Не оплачен)"),
        "partial": ("eq", "Исполнен(Частично)"),
    }
    if tag in statuses:
        op, status = statuses[tag]
        return QueryPlan(
            kind="aggregate",
            language=language,
            metrics=("count",),
            filters=(Filter(field="status", op=op, values=(status,)),),
        )
    if tag in ("buyer_tonnes_2025", "seller_tonnes_2025"):
        role = "buyer_inn" if tag.startswith("buyer") else "seller_inn"
        filters += [
            Filter(field="tn_ved_code", op="eq", values=("252329",)),
            Filter(field="unit", op="eq", values=("тонна",)),
        ]
        return QueryPlan(
            kind="aggregate",
            language=language,
            metrics=("sum_volume",),
            filters=tuple(filters),
            group_by=(role,),
            order_by=(Order(field="sum_volume"),),
            limit=1,
        )
    if tag in ("sum_uzs_2025", "sum_usd_2025", "avg_uzs_2025"):
        if tag == "sum_usd_2025":
            filters.append(Filter(field="currency", op="eq", values=("Доллар США",)))
        return QueryPlan(
            kind="aggregate",
            language=language,
            metrics=("avg_amount" if tag.startswith("avg") else "sum_amount",),
            money_mode="original" if tag == "sum_usd_2025" else "uzs",
            filters=tuple(filters),
        )
    lookups = {
        "lookup_tx": ("transaction", 100001),
        "lookup_contract": ("contract", 100001),
        "lookup_stir": ("company", "915688255"),
        "lookup_broker": ("broker", "BK001"),
    }
    if tag in lookups:
        entity, identifier = lookups[tag]
        return QueryPlan(
            kind="lookup", language=language, lookup=Lookup(entity=entity, identifier=identifier)
        )
    if tag == "code_count_2025":
        filters.append(Filter(field="tn_ved_code", op="eq", values=("252329",)))
        return QueryPlan(
            kind="aggregate", language=language, metrics=("count",), filters=tuple(filters)
        )
    raise AssertionError("Unknown fixed oracle tag")
