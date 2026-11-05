"""Fixed source mapping. Only names actually present in the authoritative CSVs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    source: str
    name: str
    sql_type: str = "VARCHAR"
    kind: str = "text"
    nullable: bool = False


# Order is the exact source header order. Never derive identifiers from a request.
SCHEMA = {
    "participants": (
        Column("ИНН", "inn", kind="inn"),
        Column("Наименование", "name"),
        Column("Регион", "region"),
        Column("Вид деятельности", "activity"),
        Column("Роль", "role"),
        Column("Плательщик НДС", "vat_payer"),
    ),
    "brokers": (
        Column("Код брокера", "broker_code", kind="broker"),
        Column("Наименование", "name"),
        Column("ИНН", "inn", kind="inn"),
        Column("Регион", "region"),
    ),
    "usd_rates": (
        Column("Дата", "rate_date", "DATE", "date"),
        Column("Курс", "usd_uzs_rate", "DECIMAL(12,2)", "money"),
    ),
    "contracts": (
        Column("Номер контракта", "contract_id", "BIGINT", "id"),
        Column("Наименование продукта", "product_name"),
        Column("Марка товара", "brand", nullable=True),
        Column("Размер товара", "size", nullable=True),
        Column("Сорт товара", "grade", nullable=True),
        Column("Тип товара", "product_type", nullable=True),
        Column("Класс товара", "product_class", nullable=True),
        Column("Код ТН ВЭД", "tn_ved_code", kind="code"),
        Column("Группа товара", "product_group"),
        Column("Категория товара", "product_category"),
        Column("Отрасль промышленности", "industry"),
        Column("Единица измерения", "unit"),
        Column("Лот", "lot_size", "BIGINT", "integer"),
        Column("Валюта", "currency"),
        Column("Базисная цена", "base_price", "DECIMAL(18,2)", "money"),
        Column("Сумма залога", "deposit_percent", "DECIMAL(5,2)", "percent"),
        Column("Базис поставки", "delivery_basis"),
        Column("Регион", "region"),
        Column("Адрес склада", "warehouse_address"),
        Column("Тип торгов", "auction_type"),
        Column("Тип контракта", "contract_type"),
        Column("Форма контракта", "contract_form"),
        Column("Срок оплаты", "payment_days", "INTEGER", "integer"),
        Column("Срок поставки", "delivery_days", "INTEGER", "integer"),
        Column("Упаковка", "packaging"),
        Column("ИНН продавца", "seller_inn", kind="inn"),
        Column("Дата регистрации", "registered_date", "DATE", "date"),
        Column("Действует до", "valid_until", "DATE", "date"),
    ),
    "deals": (
        Column("Номер сделки", "deal_id", "BIGINT", "id"),
        Column("Дата сделки", "deal_date", "DATE", "date"),
        Column("Время сделки", "deal_time", "TIME", "time"),
        Column("Тип торгов", "auction_type"),
        Column("Количество", "quantity", "BIGINT", "integer"),
        Column("Сумма сделки", "amount", "DECIMAL(18,2)", "money"),
        Column("Стартовая цена", "starting_price", "DECIMAL(18,2)", "money"),
        Column("Номер контракта", "contract_id", "BIGINT", "id"),
        Column("Наименование товара", "product_description"),
        Column("Лот", "lot_size", "BIGINT", "integer"),
        Column("Единица измерения", "unit"),
        Column("Регион", "region"),
        Column("Тип контракта", "contract_type"),
        Column("Форма контракта", "contract_form"),
        Column("Состояние сделки", "status"),
        Column("ИНН продавца", "seller_inn", kind="inn"),
        Column("ИНН покупателя", "buyer_inn", kind="inn"),
        Column("Брокер продавца", "seller_broker_code", kind="broker"),
        Column("Брокер покупателя", "buyer_broker_code", kind="broker"),
        Column("Дата оплаты", "payment_date", "DATE", "date", True),
        Column("Дата поставки", "delivery_date", "DATE", "date", True),
        Column("Поставлено", "delivered_lots", "BIGINT", "integer", True),
    ),
}
PRIMARY_KEYS = {
    "participants": "inn",
    "brokers": "broker_code",
    "usd_rates": "rate_date",
    "contracts": "contract_id",
    "deals": "deal_id",
}
EXPECTED_COUNTS = {
    "deals": 500000,
    "contracts": 6616,
    "participants": 14392,
    "brokers": 120,
    "usd_rates": 1765,
}
YEAR_COUNTS = {2022: 84299, 2023: 93985, 2024: 106647, 2025: 115763, 2026: 99306}
UNITS = ("килограмм", "тонна", "литр", "метр", "кв.метр", "куб.метр", "штука")
STATUSES = {
    "Новый": "Concluded on snapshot day 2026-10-30",
    "Не подписан": "Not yet signed by the parties",
    "Заключен": "Forward/futures signed; payment deadline not expired",
    "Ждёт оплату": "Spot signed; payment deadline not expired",
    "Оплачен": "Paid, not yet delivered",
    "Исполнен": "Paid and delivered in full",
    "Исполнен(Частично)": "Paid and partly delivered; delivered_lots is evidence",
    "Аннулирован(Не оплачен)": "Unpaid by deadline and cancelled; trade not fulfilled",
}
# All relationships have been observed in the source, not inferred from names.
JOINS = (
    ("deals", "contract_id", "contracts", "contract_id"),
    ("deals", "seller_inn", "participants", "inn"),
    ("deals", "buyer_inn", "participants", "inn"),
    ("deals", "seller_broker_code", "brokers", "broker_code"),
    ("deals", "buyer_broker_code", "brokers", "broker_code"),
    ("deals", "deal_date", "usd_rates", "rate_date"),
    ("contracts", "seller_inn", "participants", "inn"),
)
