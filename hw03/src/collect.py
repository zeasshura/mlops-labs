"""SQuAD 1.1 → проверенные chat-примеры по абзацам Википедии."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from src.config import load_params, source_files


def pick_prompt(example_id: str, variants: list[str]) -> str:
    digest = hashlib.sha1(example_id.encode("utf-8")).digest()
    return variants[int.from_bytes(digest, "big") % len(variants)]


def selected_articles(articles: list[dict], limit: int) -> list[dict]:
    """Стабильная выборка статей, независимая от порядка в исходном JSON."""
    if limit <= 0:
        raise ValueError("collect.article_limits должны быть положительными")
    return sorted(
        articles,
        key=lambda article: (hashlib.sha256(article["title"].encode("utf-8")).hexdigest(), article["title"]),
    )[:limit]


def verified_answer(qa: dict, context: str, verify: bool) -> tuple[str | None, str]:
    """Найти первый непустой ответ, чей offset точно указывает в абзац."""
    if not qa.get("answers"):
        return None, "no_answer"
    for answer in qa["answers"]:
        text = answer.get("text", "").strip()
        start = answer.get("answer_start")
        if not text:
            continue
        if not verify or (isinstance(start, int) and start >= 0 and context[start : start + len(text)] == text):
            return text, "ok"
    return None, "invalid_span"


def main() -> None:
    params = load_params()
    cfg = params["collect"]
    prompts = cfg["system_prompts"]
    if len(prompts) < 3:
        raise SystemExit("collect.system_prompts: нужны хотя бы три варианта")
    sources = source_files(params)
    out = Path(params["paths"]["raw"])
    out.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    groups: set[str] = set()
    used_prompts: set[str] = set()
    ids: set[str] = set()

    with out.open("w", encoding="utf-8") as dst:
        for source in sources:
            payload = json.loads(source.read_text(encoding="utf-8"))
            if payload.get("version") != "1.1" or not isinstance(payload.get("data"), list):
                raise ValueError(f"{source}: ожидается официальный JSON SQuAD 1.1")
            limit = cfg["article_limits"][source.name]
            articles = selected_articles(payload["data"], limit)
            counts["articles_selected"] += len(articles)
            for article in articles:
                title = article["title"]
                for paragraph in article["paragraphs"]:
                    context = paragraph["context"]
                    for qa in paragraph["qas"]:
                        counts["questions_scanned"] += 1
                        answer, reason = verified_answer(qa, context, cfg["verify_answer_span"])
                        if answer is None:
                            counts[f"dropped_{reason}"] += 1
                            continue
                        example_id = qa["id"]
                        if example_id in ids:
                            counts["dropped_duplicate_id"] += 1
                            continue
                        ids.add(example_id)
                        prompt = pick_prompt(example_id, prompts)
                        used_prompts.add(prompt)
                        groups.add(title)
                        row = {
                            "id": example_id,
                            "topic": title,
                            "messages": [
                                {"role": "system", "content": prompt},
                                {"role": "user", "content": f"Article: {title}\nPassage: {context}\nQuestion: {qa['question']}"},
                                {"role": "assistant", "content": answer},
                            ],
                        }
                        dst.write(json.dumps(row, ensure_ascii=False) + "\n")
                        counts["rows_written"] += 1

    metrics = {
        "version": cfg["version"],
        "source_files": len(sources),
        "groups": len(groups),
        "system_prompt_variants": len(used_prompts),
        **dict(counts),
    }
    target = Path(params["paths"]["metrics_collect"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"collect: {cfg['version']}, вопросов {counts['questions_scanned']}, "
          f"проверенных ответов {counts['rows_written']}, статей {len(groups)} → {out}")


if __name__ == "__main__":
    main()
