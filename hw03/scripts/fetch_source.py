#!/usr/bin/env python3
"""Скачать официальные файлы SQuAD 1.1 и проверить SHA-256."""

import hashlib
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sources"
BASE = "https://rajpurkar.github.io/SQuAD-explorer/dataset"
FILES = {
    "train-v1.1.json": "3527663986b8295af4f7fcdff1ba1ff3f72d07d61a20f487cb238a6ef92fd955",
    "dev-v1.1.json": "95aa6a52d5d6a735563366753ca50492a658031da74f301ac5238b03966972c9",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    SOURCE.mkdir(parents=True, exist_ok=True)
    for name, checksum in FILES.items():
        target = SOURCE / name
        if target.is_file() and sha256(target) == checksum:
            print(f"{name}: уже загружен и проверен")
            continue
        temporary = target.with_suffix(target.suffix + ".part")
        try:
            with urllib.request.urlopen(f"{BASE}/{name}", timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            actual = sha256(temporary)
            if actual != checksum:
                raise ValueError(f"{name}: SHA-256 {actual} не совпадает с {checksum}")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"{name}: загружен и проверен")


if __name__ == "__main__":
    main()
