"""Conservative lexical/script gate and non-authoritative normalization hints."""

import re
import unicodedata
from dataclasses import dataclass

from app.agent.entity_resolver import normalize

QUOTED = re.compile(r'"[^"\n]{0,256}"|«[^»\n]{0,256}»|“[^”\n]{0,256}”')
UZ = frozenset(
    (
        "nechta necha qancha qanca bitim bitimlar bitimlarni soni jami summa yilda yil "
        "yilgi oy oyda oldin keyin dan eng kop koproq sotgan sotuvchi sotuvchilar xaridor "
        "xaridorlar olgan sotib oluvchi qaysi firma barcha faqat bajarilgan bajarilmagan "
        "bekor qilingan kerak emas emasmi demadim bolgan korsat korsating topib ber "
        "menga manga menga mn men kkmas boyicha tonnada hajm miqdor qiymat soxta "
        "narx ortacha narxi shartnoma haqida bugun kecha bu yil otgan shular undan "
        "ularni emasligini shart agar hamda tolangan tolov yetkazilgan mos katta "
        "kichik umumiy sttr nechta kiril uchun hisobla chiqar quvilmagan menga"
    ).split()
)
RU = frozenset(
    (
        "skolko sdelok sdelki sdelka sdelku kolichestvo summa summu summe obshchaya "
        "za god godu goda mesyats vse tolko ispolnennie ispolnennye otmenennye "
        "pokazhi pokazat kompanii kompaniya kupila kupili prodala prodali prodavets "
        "pokupatel pokupateli prodavtsi naibolshe naibolshaya maksimalnaya posle do "
        "broker dogovor kontrakt nomen kod srednyaya ne nuzhno nado esli segodnya "
        "vchera etom proshlom obyom tonnakh tsene tsenu inn postavleno sravni"
    ).split()
)
RU = RU | frozenset(
    normalize(w)
    for w in (
        "покажи покажите сделки сделок сколько какая какой купила купил продала продал "
        "выполненные исполненные сумма суммы объём объема общее количество год году "
        "года до после все только нужно надо договор договора контракт номер номера"
    ).split()
)
EN = frozenset(
    (
        "how many transactions show transaction total which buyer seller please count "
        "what where when company exchange amount before after"
    ).split()
)
OTHER = frozenset(
    (
        "kaç işlem işlemler nedir hola cuantas transacciones bonjour combien "
        "danke wie viele cuantos"
    ).split()
)


@dataclass(frozen=True)
class LanguageHint:
    language: str | None
    disposition: str  # route | unsupported | ambiguous


def outside_names(text: str) -> str:
    return QUOTED.sub(" ", text)


def detect_language(question: str) -> LanguageHint:
    plain = outside_names(question)
    words = set(normalize(plain).split())
    uz = len(words & (UZ - {"summa", "firma", "broker"}))
    ru = len(words & RU)
    original = plain.casefold()
    if any(
        unicodedata.name(c, "").startswith(
            ("ARABIC", "CJK", "HIRAGANA", "KATAKANA", "HANGUL", "DEVANAGARI")
        )
        for c in plain
    ):
        return LanguageHint(None, "unsupported")
    if (set(re.findall(r"\w+", original)) & OTHER or words & EN) and uz == 0:
        return LanguageHint(None, "unsupported")
    if uz:
        cyr_words = re.findall(r"[а-яёўқғҳ]+", original)
        lat_words = re.findall(r"[a-z]+", original)
        cyr_uz = sum(normalize(w) in UZ for w in cyr_words)
        lat_uz = sum(normalize(w) in UZ for w in lat_words)
        if cyr_uz or re.search("[ўқғҳ]", original):
            if cyr_uz >= lat_uz:
                return LanguageHint("uz_cyrl", "route")
        # Uzbek grammar wins over embedded Russian business terms.
        return LanguageHint("uz_latn", "route")
    if ru:
        if re.fullmatch(r"\s*broker\s*[:№#]?\s*BK[0-9]{3}\s*", plain, re.I):
            return LanguageHint("uz_latn", "route")
        return LanguageHint("ru", "route")
    if words & {"summa", "firma", "broker"} and re.search("[a-z]", original):
        return LanguageHint("uz_latn", "route")
    if re.fullmatch(r"\s*(?:STIR|sttr)\s*[:№#]?\s*[0-9]{9}\s*", plain, re.I):
        return LanguageHint("uz_latn", "route")
    if re.fullmatch(r"\s*(?:СТИР|стир)\s*[:№#]?\s*[0-9]{9}\s*", plain, re.I):
        return LanguageHint("uz_cyrl", "route")
    if any(c.isalpha() for c in plain):
        # Let the primary semantic model classify unfamiliar Latin/Cyrillic wording.
        return LanguageHint(None, "route")
    return LanguageHint(None, "ambiguous")


def conservative_normalize(question: str) -> str:
    """Only provide a hint. Original text remains authoritative and is always sent intact.

    Quoted names, uppercase abbreviations and everything not in a tiny token map remain
    byte-for-byte unchanged. No role, year, range operator or negation is deleted.
    """
    replacements = {
        "mn": "men",
        "manga": "menga",
        "qanca": "qancha",
        "kop": "ko'p",
        "kkmas": "kerak emas",
    }
    spans = []
    offset = 0
    for match in QUOTED.finditer(question):
        spans.append(_normalize_fragment(question[offset : match.start()], replacements))
        spans.append(match.group())
        offset = match.end()
    spans.append(_normalize_fragment(question[offset:], replacements))
    return "".join(spans)


def _normalize_fragment(fragment, replacements):
    def replace(match):
        word = match.group()
        return replacements.get(word, word) if word.islower() else word

    value = re.sub(r"\b[a-zA-Z]+\b", replace, fragment)
    return re.sub(r"\bsttr\b(?=\s*[:№#]?\s*[0-9]{9}\b)", "STIR", value)
