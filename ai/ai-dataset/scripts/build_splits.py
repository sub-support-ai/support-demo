"""
Build stratified train/val/test splits by (department, priority).

Usage:
    python scripts/build_splits.py --run-id v1 --train 0.8 --val 0.1 --test 0.1 --seed 42

Inputs:  data/processed/<run_id>/dedup.jsonl
Outputs: data/splits/<run_id>/{train,val,test}.jsonl
         data/splits/<run_id>/distribution.json
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict

from scripts._common import ROOT, append_jsonl, read_jsonl


def stratify_key(record: dict) -> str:
    labels = record["sample"]["labels"]
    return f"{labels['department']}|{labels['priority']}"


def split_records(
    records: list[dict], train: float, val: float, test: float, seed: int
) -> tuple[list[dict], list[dict], list[dict]]:
    assert abs(train + val + test - 1.0) < 1e-6, "ratios must sum to 1.0"
    rng = random.Random(seed)

    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        buckets[stratify_key(r)].append(r)

    train_set: list[dict] = []
    val_set: list[dict] = []
    test_set: list[dict] = []

    for key, items in buckets.items():
        rng.shuffle(items)
        n = len(items)
        n_train = int(round(n * train))
        n_val = int(round(n * val))
        train_set.extend(items[:n_train])
        val_set.extend(items[n_train : n_train + n_val])
        test_set.extend(items[n_train + n_val :])

    rng.shuffle(train_set)
    rng.shuffle(val_set)
    rng.shuffle(test_set)
    return train_set, val_set, test_set


def distribution(records: list[dict]) -> dict:
    by_dept = Counter(r["sample"]["labels"]["department"] for r in records)
    by_cat = Counter(r["sample"]["labels"]["category"] for r in records)
    by_prio = Counter(r["sample"]["labels"]["priority"] for r in records)
    return {
        "total": len(records),
        "by_department": dict(by_dept),
        "by_category": dict(by_cat),
        "by_priority": dict(by_prio),
    }


def run(args: argparse.Namespace) -> None:
    src = ROOT / "data" / "processed" / args.run_id / "dedup.jsonl"
    out_dir = ROOT / "data" / "splits" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    records = read_jsonl(src)
    if not records:
        print(f"ERROR: no records in {src}")
        return

    train, val, test = split_records(
        records, args.train, args.val, args.test, args.seed
    )

    for name, recs in [("train", train), ("val", val), ("test", test)]:
        path = out_dir / f"{name}.jsonl"
        path.unlink(missing_ok=True)
        for r in recs:
            append_jsonl(path, r)
        print(f"  {name}: {len(recs)} -> {path}")

    dist = {
        "train": distribution(train),
        "val": distribution(val),
        "test": distribution(test),
        "seed": args.seed,
        "ratios": {"train": args.train, "val": args.val, "test": args.test},
    }
    (out_dir / "distribution.json").write_text(
        json.dumps(dist, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\ndistribution: {out_dir / 'distribution.json'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--train", type=float, default=0.8)
    parser.add_argument("--val", type=float, default=0.1)
    parser.add_argument("--test", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
