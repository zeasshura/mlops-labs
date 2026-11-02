"""Маскирование почты, телефона и дат рождения во входе и ответе."""

import re

# Номер ищем после контактного маркера, чтобы не маскировать числа из статьи.
PHONE = re.compile(
    r"\b(?:phone|telephone|mobile|tel)\s*[:\-]?\s*"
    r"(?:\+\d{1,3}[\s.\-]*)?\(?\d{3}\)?[\s.\-]*\d{3}[\s.\-]*\d{4}\b",
    re.IGNORECASE,
)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
BIRTH_DATE = re.compile(
    r"(?P<pre>(?:date of birth|born on|birth date)\s*[:\-—]?\s*)"
    r"(?:0?[1-9]|[12]\d|3[01])[.\-/](?:0?[1-9]|1[0-2])[.\-/](?:19|20)\d{2}\b",
    re.IGNORECASE,
)

PATTERNS: dict[str, re.Pattern[str]] = {
    "phone": PHONE,
    "email": EMAIL,
    "birth_date": BIRTH_DATE,
}
# Шаблон замены, а не просто строка: у даты надо сохранить маркер
# («дата рождения»), иначе вместе с ПДн из примера уходит смысл.
PLACEHOLDERS: dict[str, str] = {
    "phone": "[PHONE]",
    "email": "[EMAIL]",
    "birth_date": r"\g<pre>[DATE]",
}


def scrub(text: str) -> tuple[str, dict[str, int]]:
    """Заменить найденные ПДн плейсхолдерами. Возвращает текст и счётчик по типам."""
    hits: dict[str, int] = {}
    for name, pattern in PATTERNS.items():
        text, count = pattern.subn(PLACEHOLDERS[name], text)
        if count:
            hits[name] = count
    return text, hits
