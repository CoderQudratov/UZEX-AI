"""RAM-only source dictionaries. Fuzzy matches are suggestions, never silent selections."""

import json
import re
import unicodedata
from pathlib import Path

from rapidfuzz import fuzz, process

from app.agent.query_models import Candidate, Resolution
from app.db.schema import STATUSES

CYR = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюяўқғҳ",
        [
            "a",
            "b",
            "v",
            "g",
            "d",
            "e",
            "yo",
            "j",
            "z",
            "i",
            "y",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "r",
            "s",
            "t",
            "u",
            "f",
            "x",
            "ts",
            "ch",
            "sh",
            "shch",
            "",
            "i",
            "",
            "e",
            "yu",
            "ya",
            "o",
            "q",
            "g",
            "h",
        ],
        strict=True,
    )
)
ALIASES = {
    "status": {
        "Новый": ("yangi", "янги"),
        "Не подписан": ("imzolanmagan", "имзоланмаган"),
        "Заключен": ("tuzilgan", "тузилган"),
        "Ждёт оплату": ("tolovni kutmoqda", "тўловни кутмоқда"),
        "Оплачен": ("tolangan", "тўланган"),
        "Исполнен": ("bajarilgan", "бажарилган"),
        "Исполнен(Частично)": ("qisman bajarilgan", "қисман бажарилган"),
        "Аннулирован(Не оплачен)": ("bekor qilingan", "бекор қилинган"),
    },
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(CYR.get(c, c) for c in text)
    # Apostrophe variants within Uzbek letters do not become word boundaries.
    text = re.sub("[‘’ʻʼ`'ъь]", "", text)
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def identity_normalize(text: str) -> str:
    """Preserve Uzbek O/G versus Oʻ/Gʻ phonemes; only equivalent apostrophes collapse."""
    text = unicodedata.normalize("NFKC", text).casefold()
    table = {**CYR, "ў": "oʻ", "ғ": "gʻ"}
    text = "".join(table.get(c, c) for c in text)
    text = re.sub(r"([og])[‘’ʻʼ`']", lambda m: m[1] + "ʻ", text)
    text = re.sub(r"(?<![og])[‘’ʼ`']", "", text)
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


class EntityResolver:
    def __init__(self, warehouse):
        self.values = {}
        queries = {
            "company": "SELECT inn,name FROM participants ORDER BY inn",
            "broker": "SELECT broker_code,name FROM brokers ORDER BY broker_code",
            "product": (
                "SELECT DISTINCT product_name,product_name FROM contracts ORDER BY product_name"
            ),
            "tn_ved": "SELECT DISTINCT tn_ved_code,tn_ved_code FROM contracts ORDER BY tn_ved_code",
            "region": "SELECT DISTINCT region,region FROM deals ORDER BY region",
        }
        with warehouse.connection() as c:
            for kind, sql in queries.items():
                self.values[kind] = tuple(
                    Candidate(value=r[0], label=r[1]) for r in c.execute(sql).fetchall()
                )
        self.values["status"] = tuple(Candidate(value=s, label=s) for s in STATUSES)
        self.identity_index = {
            kind: tuple((identity_normalize(c.label), c.label) for c in values)
            for kind, values in self.values.items()
        }
        self.index = {}
        for kind, values in self.values.items():
            index = {}
            for candidate in values:
                for text in (candidate.value, candidate.label):
                    index.setdefault(normalize(text), set()).add((candidate.value, candidate.label))
            self.index[kind] = index
        regions = json.loads(
            Path(__file__).parents[1].joinpath("db/source_regions.json").read_text()
        )
        for uz, ru in regions.items():
            self.index["region"].setdefault(normalize(ru), set()).add((uz, uz))
        # Curated family translations only point to actually observed product strings.
        # Multiple recorded variants remain multiple candidates, never merged.
        for russian, uzbek in {
            "пшеница": "bugdoy",
            "мука": "un",
            "цемент": "sement",
            "уголь": "komir",
            "масло хлопковое": "paxta yogi",
            "бензин": "benzin",
            "дизельное топливо": "dizel yoqilgisi",
            "сахар": "shakar",
            "карбамид": "karbamid",
            "арматура": "armatura",
            "кирпич": "gisht",
        }.items():
            candidates = {
                (c.value, c.label)
                for c in self.values["product"]
                if normalize(c.value).startswith(normalize(russian))
            }
            if candidates:
                self.index["product"].setdefault(normalize(uzbek), set()).update(candidates)
        for value, aliases in ALIASES["status"].items():
            for alias in aliases:
                self.index["status"].setdefault(normalize(alias), set()).add((value, value))

    def resolve(self, kind: str, text: str) -> Resolution:
        if kind not in self.index:
            return Resolution(status="UNSUPPORTED", reason="ENTITY_KIND")
        if not isinstance(text, str) or not 1 <= len(text) <= 256:
            return Resolution(status="UNSUPPORTED", reason="ENTITY_LENGTH")
        key = normalize(text)
        if not key:
            return Resolution(status="NOT_FOUND", reason="ENTITY_ABSENT")
        matched = self.index[kind].get(key, set())
        if matched:
            exact = matched
            if kind in ("company", "broker", "product", "tn_ved"):
                exact = {
                    (value, label)
                    for value, label in matched
                    if identity_normalize(text)
                    in (identity_normalize(value), identity_normalize(label))
                }
            if len(exact) == 1:
                value, label = next(iter(exact))
                return Resolution(
                    status="VERIFIED",
                    candidates=(Candidate(value=value, label=label),),
                    reason="EXACT",
                )
            selected = exact or matched
            return Resolution(
                status="AMBIGUOUS",
                reason="COLLISION" if exact else "CONFIRM_NORMALIZATION",
                candidates=tuple(
                    Candidate(value=v, label=label) for v, label in sorted(selected)[:10]
                ),
            )
        # Identifiers never use approximate matching.
        if kind == "tn_ved" or text.isdecimal() or re.fullmatch("BK[0-9]+", text.upper()):
            return Resolution(status="NOT_FOUND", reason="ENTITY_ABSENT")
        suggestions = process.extract(
            key, tuple(sorted(self.index[kind])), scorer=fuzz.WRatio, score_cutoff=82, limit=5
        )
        plausible = set()
        for candidate, _score, _ in suggestions:
            plausible.update(self.index[kind][candidate])
        if plausible:
            return Resolution(
                status="AMBIGUOUS",
                reason="CONFIRM_FUZZY",
                candidates=tuple(
                    Candidate(value=v, label=label) for v, label in sorted(plausible)[:10]
                ),
            )
        return Resolution(status="NOT_FOUND", reason="ENTITY_ABSENT")
