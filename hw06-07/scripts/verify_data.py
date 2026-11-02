"""Verify the raw training index against HW4 tokenizer output, not text guesses."""
import hashlib
import json
import sys
from pathlib import Path
import torch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation.contract import read_rows, validate_golden

root = Path(__file__).resolve().parents[1]
raw = read_rows(root.parent / 'hw04/data/train.jsonl')
index = read_rows(root / 'data/eval/training-index.jsonl')
blob = torch.load(root / 'data/tokenized/train.pt', weights_only=True)
raw_ids = {r['id'] for r in raw}
index_ids = {r['id'] for r in index}
tensor_ids = {r['id'] for r in blob['examples']}
assert len(raw) == len(index) and raw_ids == index_ids
by_id = {r['id']: r for r in index}
assert all(by_id[r['id']]['input'] == next(m['content'] for m in r['messages'] if m['role'] == 'user')
           and by_id[r['id']]['group_id'] == r['topic'] for r in raw)
assert tensor_ids <= raw_ids
hash_file = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
for name in ('train.pt', 'val.pt'):
    assert hash_file(root / 'data/tokenized' / name) == hash_file(root.parent / 'hw04/data/tokenized' / name)
golden, behavior = (read_rows(root / 'data/eval' / n) for n in ('golden.jsonl','behavioral.jsonl'))
proof = validate_golden(golden, index, behavior)
proof.update(raw_train_rows=len(raw), tokenized_train_rows=len(blob['examples']),
             dropped_by_hw4_tokenizer=len(raw_ids - tensor_ids), all_tensor_ids_in_raw=True,
             tensor_hashes_match_hw4=True,
             note='HW4 dropped 79 rows without supervised answer tokens; full raw index retains these rows.')
(root / 'docs/data_validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(proof,ensure_ascii=False,indent=2))
