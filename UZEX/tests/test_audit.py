import io
from decimal import Decimal
import zipfile

import pytest
from tools.audit_data import decimal_value, date_value, safe_members


@pytest.mark.parametrize(('raw', 'expected'), [('304 547 938.4', '304547938.4'), ('0.01', '0.01'), ('1', '1'), ('-1', '-1')])
def test_exact_decimals(raw, expected):
    assert decimal_value(raw) == Decimal(expected)


@pytest.mark.parametrize('raw', ['NaN', 'Infinity', '1e9', '1,23', '12 34', '', ' 1', '1 ', '1_000', '1' * 81])
def test_reject_bad_decimal(raw):
    with pytest.raises(ValueError):
        decimal_value(raw)


def test_financial_precision():
    assert decimal_value('99999999999999.99') + decimal_value('0.01') == Decimal('100000000000000.00')


@pytest.mark.parametrize('raw', ['31.02.2026', '2026-10-30', '1.1.2026'])
def test_reject_bad_date(raw):
    with pytest.raises(ValueError):
        date_value(raw)


def test_date():
    assert date_value('30.10.2026').isoformat() == '2026-10-30'


@pytest.mark.parametrize('members', [['../README.md'], ['/README.md'], ['a\\README.md'], ['README.md', 'extra.csv'], ['README.md', 'other/README.md'], []])
def test_reject_archive(members):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for member in members:
            archive.writestr(member, 'x')
    with zipfile.ZipFile(stream) as archive, pytest.raises(ValueError):
        safe_members(archive, set())


def test_archive_allowed():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('dataset/README.md', 'x')
        archive.writestr('dataset/test.csv', 'x')
    with zipfile.ZipFile(stream) as archive:
        assert safe_members(archive, {'test.csv'}) == {'README.md': 'dataset/README.md', 'test.csv': 'dataset/test.csv'}


def test_missing_delivery_is_unknown():
    from tools.audit_data import numeric_value
    assert numeric_value('Поставлено', '') is None
    assert numeric_value('Поставлено', '0') == Decimal(0)
    with pytest.raises(ValueError):
        numeric_value('Сумма сделки', '')


def test_recorded_region_pair():
    from tools.audit_data import regions_match
    assert regions_match('Toshkent shahri', 'г. Ташкент')
    assert not regions_match('Toshkent shahri', 'Ташкентская область')
    assert not regions_match('unknown', 'unknown')
