"""Нормализация текста и шинглы — общие для очистки, сплита и проверки контаминации.

Один модуль на все три стадии специально: если нормализация разъедется,
дедупликация и проверка контаминации начнут мерить разные вещи, и проверка
станет зелёной при реальном пересечении.
"""

import re
import unicodedata

_SPACES = re.compile(r"\s+")
_DASHES = str.maketrans({"—": "-", "–": "-", "‑": "-", " ": " "})


def normalize_text(text: str) -> str:
    """Каноническая форма строки: NFKC, единые тире, схлопнутые пробелы, нижний регистр."""
    text = unicodedata.normalize("NFKC", text).translate(_DASHES)
    return _SPACES.sub(" ", text).strip().lower()


def normalize_group(topic: str) -> str:
    """Каноническая форма заголовка статьи — ключ группы для сплита."""
    return normalize_text(topic)


def question_text(user: str) -> str:
    """Выделить сам вопрос: абзац статьи не определяет дубль."""
    if "Question:" in user:
        return normalize_text(user.rsplit("Question:", 1)[1])
    return normalize_text(user)


def shingles(text: str, size: int) -> set[str]:
    """Множество словных n-грамм — вход для MinHash."""
    words = re.findall(r"\w+", text)
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}
