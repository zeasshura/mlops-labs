"""Точные повторы и почти-дубли вопросов.

LSH быстро ищет кандидатов, точный Жаккар словных шинглов решает, удалять ли их.
Это не позволяет ошибке MinHash снизить фактический порог очистки.
"""

from typing import Sequence

from datasketch import MinHash, MinHashLSH

from src.textnorm import shingles


def build_minhash(text: str, shingle_words: int, num_perm: int) -> MinHash:
    mh = MinHash(num_perm=num_perm)
    mh.update_batch([s.encode("utf-8") for s in shingles(text, shingle_words)])
    return mh


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def exact_duplicates(keys: Sequence[str]) -> list[int]:
    """Индексы повторных вхождений. Первое вхождение остаётся."""
    seen: set[str] = set()
    dupes: list[int] = []
    for i, key in enumerate(keys):
        if key in seen:
            dupes.append(i)
        else:
            seen.add(key)
    return dupes


def near_duplicates(
    texts: Sequence[str], shingle_words: int, num_perm: int, threshold: float
) -> list[int]:
    """Индексы почти-дублей: жадный проход, первый представитель кластера остаётся.

    LSH выдаёт кандидатов, которых дополнительно проверяет точный Жаккар.
    """
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    dupes: list[int] = []
    retained: dict[int, set[str]] = {}
    for i, text in enumerate(texts):
        mh = build_minhash(text, shingle_words, num_perm)
        current = shingles(text, shingle_words)
        if any(jaccard(current, retained[int(key)]) >= threshold for key in lsh.query(mh)):
            dupes.append(i)
        else:
            lsh.insert(str(i), mh)
            retained[i] = current
    return dupes


def cross_near_duplicates(
    left: Sequence[str],
    right: Sequence[str],
    shingle_words: int,
    num_perm: int,
    threshold: float,
) -> list[tuple[int, int]]:
    """Пары (индекс в left, индекс в right) с Жаккаром выше порога.

    Используется проверкой контаминации: точное совпадение текстов ловит
    копипасту, а протекают обычно парафразы.
    """
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    left_shingles = [shingles(text, shingle_words) for text in left]
    for i, text in enumerate(left):
        lsh.insert(str(i), build_minhash(text, shingle_words, num_perm))
    pairs: list[tuple[int, int]] = []
    for j, text in enumerate(right):
        current = shingles(text, shingle_words)
        for key in sorted(lsh.query(build_minhash(text, shingle_words, num_perm)), key=int):
            i = int(key)
            if jaccard(left_shingles[i], current) >= threshold:
                pairs.append((i, j))
    return pairs
