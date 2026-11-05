import pytest

from app.agent.answer_formatter import format_answer
from app.agent.query_models import VerifiedResult


@pytest.mark.parametrize(
    ("language", "status", "expected"),
    [
        ("uz-Latn", "NOT_FOUND", "Mos ma’lumot topilmadi."),
        ("uz-Cyrl", "NOT_FOUND", "Мос маълумот топилмади."),
        ("ru", "NOT_FOUND", "Совпадающие данные не найдены."),
        ("uz-Latn", "AMBIGUOUS", "So‘rov noaniq. Aniqlashtirish kerak."),
        ("uz-Cyrl", "AMBIGUOUS", "Сўров ноаниқ. Аниқлаштириш керак."),
        ("ru", "AMBIGUOUS", "Запрос неоднозначен. Требуется уточнение."),
        ("uz-Latn", "UNSUPPORTED", "Bu so‘rov qo‘llab-quvvatlanmaydi."),
        ("uz-Cyrl", "UNSUPPORTED", "Бу сўров қўллаб-қувватланмайди."),
        ("ru", "UNSUPPORTED", "Этот запрос не поддерживается."),
        ("uz-Latn", "ERROR", "So‘rovni bajarib bo‘lmadi. Qayta urinib ko‘ring."),
        ("uz-Cyrl", "ERROR", "Сўровни бажариб бўлмади. Қайта уриниб кўринг."),
        ("ru", "ERROR", "Не удалось выполнить запрос. Повторите попытку."),
    ],
)
def test_safe_status_templates(language, status, expected):
    result = VerifiedResult(status=status, dataset_version="fixture-source")
    assert format_answer(result, language) == expected
