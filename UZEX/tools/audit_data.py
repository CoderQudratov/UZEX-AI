"""Offline, read-only audit of the authoritative archive. Never processes chat data."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COUNTS = {'contracts.csv': 6616, 'participants.csv': 14392, 'brokers.csv': 120,
                   **{f'deals_{y}.csv': n for y, n in zip(range(2022, 2027), (84299, 93985, 106647, 115763, 99306))}}
REGION_PAIRS = json.loads((ROOT / 'schema/source_regions.json').read_text(encoding='utf-8'))
NUMBER = re.compile(r'-?(?:\d+|\d{1,3}(?: \d{3})+)(?:\.\d+)?', re.ASCII)
MONEY = ('Сумма сделки', 'Стартовая цена', 'Базисная цена', 'Курс')
NUMERIC = MONEY + ('Количество', 'Лот', 'Поставлено', 'Срок оплаты', 'Срок поставки')
DATES = ('Дата', 'Дата сделки', 'Дата оплаты', 'Дата поставки', 'Дата регистрации', 'Действует до')
STATUSES = {'Новый', 'Не подписан', 'Заключен', 'Ждёт оплату', 'Оплачен', 'Исполнен',
            'Исполнен(Частично)', 'Аннулирован(Не оплачен)'}


def decimal_value(value: str) -> Decimal:
    if len(value) > 80 or not NUMBER.fullmatch(value):
        raise ValueError('Invalid decimal syntax')
    try:
        result = Decimal(value.replace(' ', ''))
    except InvalidOperation as exc:
        raise ValueError('Invalid decimal') from exc
    if not result.is_finite():
        raise ValueError('Nonfinite decimal')
    return result


def numeric_value(field: str, value: str) -> Decimal | None:
    # Empty delivered lots are missing evidence, never an asserted zero.
    if field == 'Поставлено' and value == '':
        return None
    return decimal_value(value)


def regions_match(deal_region: str, contract_region: str) -> bool:
    return REGION_PAIRS.get(deal_region) == contract_region


def date_value(value: str):
    if not re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', value, re.ASCII):
        raise ValueError('Invalid date syntax')
    return datetime.strptime(value, '%d.%m.%Y').date()


def safe_members(archive: zipfile.ZipFile, expected: set[str]) -> dict[str, str]:
    members = {}
    total = 0
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or '..' in path.parts or '\\' in info.filename:
            raise ValueError('Unsafe archive path')
        total += info.file_size
        if total > 500_000_000 or info.file_size > 200_000_000:
            raise ValueError('Archive size limit')
        if info.is_dir():
            continue
        if path.name not in expected | {'README.md'} or path.name in members:
            raise ValueError('Unexpected or duplicate member')
        members[path.name] = info.filename
    if set(members) != expected | {'README.md'}:
        raise ValueError('Missing archive member')
    return members


def audit(source: Path, schema_path: Path = ROOT / 'schema/source_headers.json') -> dict:
    start = time.perf_counter()
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    errors, warnings = Counter(), Counter()
    profiles = {}
    maps = {}
    ids = set()
    observed_dates = set()
    currencies, statuses, units = Counter(), Counter(), Counter()
    sums = Counter()
    converted = Decimal(0)
    minimum = maximum = previous = None
    decimal_profiles = {}
    with source.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    with zipfile.ZipFile(source) as archive, localcontext() as ctx:
        ctx.prec = 60
        members = safe_members(archive, set(schema))
        for name in ['participants.csv', 'brokers.csv', 'usd_rates.csv', 'contracts.csv'] + sorted(n for n in schema if n.startswith('deals_')):
            key = {'participants.csv': 'ИНН', 'brokers.csv': 'Код брокера', 'usd_rates.csv': 'Дата'}.get(name, 'Номер контракта' if name == 'contracts.csv' else 'Номер сделки')
            count = 0
            nulls = Counter()
            table = {}
            with archive.open(members[name]) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8-sig', newline=''))
                if reader.fieldnames != schema[name]:
                    raise ValueError(f'Header mismatch: {name}')
                for row in reader:
                    count += 1
                    def check(condition, label):
                        if not condition:
                            errors[f'{name}:{label}'] += 1
                    if None in row or any(v is None for v in row.values()):
                        errors[f'{name}:row_width'] += 1
                        continue
                    nulls.update(k for k, v in row.items() if v == '')
                    check(bool(row[key]), 'empty_primary_key')
                    if name.startswith('deals_'):
                        check(row[key] not in ids, 'duplicate_primary_key')
                        ids.add(row[key])
                    else:
                        check(row[key] not in table, 'duplicate_primary_key')
                        table[row[key]] = row
                    for field in ('ИНН', 'ИНН продавца', 'ИНН покупателя'):
                        if field in row:
                            check(bool(re.fullmatch(r'[0-9]{9}', row[field])), f'invalid:{field}')
                    nums, dates = {}, {}
                    for field in NUMERIC:
                        if field in row:
                            try:
                                value = numeric_value(field, row[field])
                                if value is None:
                                    continue
                                nums[field] = value
                                check(value >= 0, f'negative:{field}')
                                if field in ('Количество', 'Лот', 'Курс'):
                                    check(value > 0, f'nonpositive:{field}')
                                if field in ('Количество', 'Поставлено', 'Срок оплаты', 'Срок поставки'):
                                    check(value == value.to_integral_value(), f'noninteger:{field}')
                                p = decimal_profiles.setdefault(field, {'max_integer_digits': 0, 'max_scale': 0})
                                p['max_integer_digits'] = max(p['max_integer_digits'], max(1, value.adjusted() + 1))
                                p['max_scale'] = max(p['max_scale'], max(0, -value.as_tuple().exponent))
                            except ValueError:
                                errors[f'{name}:invalid_decimal:{field}'] += 1
                    for field in DATES:
                        if field in row:
                            if not row[field] and field in ('Дата оплаты', 'Дата поставки'):
                                continue
                            try:
                                dates[field] = date_value(row[field])
                            except ValueError:
                                errors[f'{name}:invalid_date:{field}'] += 1
                    if name == 'usd_rates.csv' and 'Дата' in dates:
                        observed_dates.add(dates['Дата'])
                    if name == 'contracts.csv':
                        check(row['ИНН продавца'] in maps['participants.csv'], 'missing_seller')
                        check(row['Валюта'] in ('Узбекский сум', 'Доллар США'), 'unknown_currency')
                        if 'Дата регистрации' in dates and 'Действует до' in dates:
                            check(dates['Дата регистрации'] <= dates['Действует до'], 'contract_date_order')
                    if not name.startswith('deals_'):
                        continue
                    contract = maps['contracts.csv'].get(row['Номер контракта'])
                    check(contract is not None, 'missing_contract')
                    for role in ('продавца', 'покупателя'):
                        participant = maps['participants.csv'].get(row[f'ИНН {role}'])
                        check(participant is not None, f'missing_participant:{role}')
                        if participant:
                            check(participant['Роль'] == {'продавца': 'Продавец', 'покупателя': 'Покупатель'}[role], f'participant_role:{role}')
                        check(row[f'Брокер {role}'] in maps['brokers.csv'], f'missing_broker:{role}')
                    check(row['Состояние сделки'] in STATUSES, 'unknown_status')
                    statuses[row['Состояние сделки']] += 1
                    units[row['Единица измерения']] += 1
                    if row['Состояние сделки'] in ('Исполнен', 'Исполнен(Частично)'):
                        check('Поставлено' in nums, 'fulfilled_without_quantity')
                    if 'Количество' in nums and 'Поставлено' in nums:
                        check(nums['Поставлено'] <= nums['Количество'], 'over_delivery')
                        state = row['Состояние сделки']
                        if state == 'Исполнен':
                            check(nums['Поставлено'] == nums['Количество'], 'fulfilled_quantity')
                        if state == 'Исполнен(Частично)':
                            check(0 < nums['Поставлено'] < nums['Количество'], 'partial_quantity')
                        if state in ('Исполнен', 'Исполнен(Частично)', 'Оплачен'):
                            check('Дата оплаты' in dates, 'paid_without_date')
                        if nums['Поставлено'] > 0:
                            check('Дата поставки' in dates, 'delivered_without_date')
                    trade_date = dates.get('Дата сделки')
                    if trade_date:
                        minimum = min(minimum, trade_date) if minimum else trade_date
                        maximum = max(maximum, trade_date) if maximum else trade_date
                        check(trade_date.year == int(name[6:10]), 'wrong_year')
                        rate = maps['usd_rates.csv'].get(row['Дата сделки'])
                        check(rate is not None, 'missing_rate')
                        try:
                            stamp = datetime.strptime(row['Дата сделки'] + ' ' + row['Время сделки'], '%d.%m.%Y %H:%M:%S')
                            if previous and stamp < previous:
                                warnings['deal_time_not_monotonic'] += 1
                            previous = stamp
                        except ValueError:
                            errors[f'{name}:invalid_time'] += 1
                        for field in ('Дата оплаты', 'Дата поставки'):
                            if field in dates:
                                check(trade_date <= dates[field] <= date_value('30.10.2026'), f'event_date_order:{field}')
                        if 'Дата оплаты' in dates and 'Дата поставки' in dates:
                            check(dates['Дата оплаты'] <= dates['Дата поставки'], 'delivery_before_payment')
                        if contract:
                            check(date_value(contract['Дата регистрации']) <= trade_date <= date_value(contract['Действует до']), 'outside_contract_validity')
                        if contract and rate and 'Сумма сделки' in nums:
                            currency = contract['Валюта']
                            currencies[currency] += 1
                            sums[currency] += nums['Сумма сделки']
                            converted += nums['Сумма сделки'] * (decimal_value(rate['Курс']) if currency == 'Доллар США' else 1)
                    if contract:
                        for field in ('Лот', 'Единица измерения', 'Регион', 'Тип торгов', 'Тип контракта', 'Форма контракта', 'ИНН продавца'):
                            check(regions_match(row[field], contract[field]) if field == 'Регион' else row[field] == contract[field], f'contract_mismatch:{field}')
                        if (contract['Тип контракта'] == 'Экспортный') != (contract['Валюта'] == 'Доллар США'):
                            warnings['export_currency_mismatch'] += 1
            profiles[name] = {'rows': count, 'columns': len(schema[name]), 'empty_values': dict(nulls)}
            if name in EXPECTED_COUNTS:
                if count != EXPECTED_COUNTS[name]:
                    errors[f'{name}:readme_count_mismatch'] += 1
            if not name.startswith('deals_'):
                maps[name] = table
        if observed_dates:
            expected_days = (max(observed_dates) - min(observed_dates)).days + 1
            if expected_days != len(observed_dates):
                errors['usd_rates:calendar_gaps'] += expected_days - len(observed_dates)
    return {'phase': 1, 'source_sha256': digest, 'source_bytes': source.stat().st_size,
            'acceptance': 'PASS' if not errors else 'FAIL', 'errors': dict(errors), 'warnings': dict(warnings),
            'files': profiles, 'deal_count': len(ids), 'deal_date_min': str(minimum), 'deal_date_max': str(maximum),
            'currencies': dict(currencies), 'statuses': dict(statuses), 'units': dict(units),
            'decimal_profiles': decimal_profiles, 'all_status_amounts_by_currency': {k: str(v) for k, v in sums.items()},
            'all_status_amount_uzs_at_trade_date_rate': str(converted),
            'usd_rate_date_min': str(min(observed_dates)) if observed_dates else None,
            'usd_rate_date_max': str(max(observed_dates)) if observed_dates else None,
            'audit_seconds': round(time.perf_counter() - start, 3),
            'notes': ['Empty delivered lots remain NULL, not zero.', 'Region aliases are fixed from observed contract links, 14 bijective pairs.', 'Synthetic source per README.', 'Totals include every status, including cancelled deals.',
                      'Offline audit timing is not API latency. No Gemini calls performed.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.archive)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'acceptance': result['acceptance'], 'deal_count': result['deal_count'],
                      'audit_seconds': result['audit_seconds'], 'errors': result['errors'], 'warnings': result['warnings']}, ensure_ascii=False))
    return 0 if result['acceptance'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
