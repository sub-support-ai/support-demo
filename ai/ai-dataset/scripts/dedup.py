"""
Near-duplicate detection via TF-IDF cosine similarity.

Treats two samples as duplicates if cosine similarity of `ticket.title + ticket.body`
is above the threshold. From each duplicate cluster, keeps the longest body (most info).

Usage:
    python scripts/dedup.py --run-id v1 --threshold 0.92

Inputs:  data/processed/<run_id>/judged.jsonl
Outputs: data/processed/<run_id>/dedup.jsonl
         data/processed/<run_id>/duplicates.jsonl
"""

from __future__ import annotations

import argparse

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from scripts._common import ROOT, append_jsonl, read_jsonl


def sample_text(record: dict) -> str:
    t = record["sample"]["ticket"]
    return f"{t['title']}\n{t['body']}"


def find_duplicate_groups(records: list[dict], threshold: float) -> list[list[int]]:
    texts = [sample_text(r) for r in records]
    vectorizer = TfidfVectorizer(min_df=1, ngram_range=(1, 2))
    matrix = vectorizer.fit_transform(texts)
    sim = cosine_similarity(matrix)
    np.fill_diagonal(sim, 0.0)

    n = len(records)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pairs = np.argwhere(sim >= threshold)
    for i, j in pairs:
        if i < j:
            union(int(i), int(j))

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]


def run(args: argparse.Namespace) -> None:
    judged_path = ROOT / "data" / "processed" / args.run_id / "judged.jsonl"
    dedup_path = ROOT / "data" / "processed" / args.run_id / "dedup.jsonl"
    dups_path = ROOT / "data" / "processed" / args.run_id / "duplicates.jsonl"

    records = read_jsonl(judged_path)
    if not records:
        print(f"ERROR: no records in {judged_path}")
        return

    print(f"loaded {len(records)} judged samples")
    groups = find_duplicate_groups(records, args.threshold)
    print(
        f"found {len(groups)} duplicate clusters covering {sum(len(g) for g in groups)} samples"
    )

    # Resumability vs idempotency: dedup is a one-shot pass over `judged.jsonl`,
    # so on re-run we want a fresh output. Otherwise repeats append.
    dedup_path.unlink(missing_ok=True)
    dups_path.unlink(missing_ok=True)

    drop_indices: set[int] = set()
    for group in groups:
        keep = max(group, key=lambda i: len(records[i]["sample"]["ticket"]["body"]))
        for idx in group:
            if idx == keep:
                continue
            drop_indices.add(idx)
            append_jsonl(
                dups_path,
                {
                    "kept_index": keep,
                    "dropped_index": idx,
                    "sample": records[idx]["sample"],
                },
            )

    kept = 0
    for i, rec in enumerate(records):
        if i in drop_indices:
            continue
        append_jsonl(dedup_path, rec)
        kept += 1

    print(f"\nkept {kept}, dropped {len(drop_indices)}")
    print(f"output:     {dedup_path}")
    print(f"duplicates: {dups_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--threshold", type=float, default=0.92)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
