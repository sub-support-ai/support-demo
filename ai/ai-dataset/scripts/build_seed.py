"""
Pick representative samples per category from an existing run and write them as
the few-shot seed for future generation. The new generation will see these
examples in its system prompt as references for style, tone, label calibration,
and step extraction.

Usage:
    python scripts/build_seed.py --from-run manual_v2 --per-category 2

Result:
    data/seed/examples.jsonl is replaced (old version backed up to .bak)
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict

from scripts._common import ROOT, read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-run", required=True, help="Run id to pick from (e.g. manual_v2).")
    parser.add_argument("--per-category", type=int, default=2, help="Samples per category.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    src = ROOT / "data" / "raw" / args.from_run / "samples.jsonl"
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src}")

    records = read_jsonl(src)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_cat[r["sample"]["labels"]["category"]].append(r["sample"])

    rng = random.Random(args.seed)
    picked: list[dict] = []
    for cat in sorted(by_cat):
        items = by_cat[cat]
        n = min(args.per_category, len(items))
        picked.extend(rng.sample(items, n))

    out = ROOT / "data" / "seed" / "examples.jsonl"
    if out.exists():
        bak = out.with_name("examples.jsonl.bak")
        bak.write_bytes(out.read_bytes())
        print(f"backed up old seed -> {bak}")

    with out.open("w", encoding="utf-8") as f:
        for sample in picked:
            f.write(json.dumps(sample, ensure_ascii=False))
            f.write("\n")

    print(f"\nwrote {len(picked)} examples to {out}")
    cnt = Counter(s["labels"]["category"] for s in picked)
    print("per-category:")
    for c, n in sorted(cnt.items()):
        print(f"  {c:25s} {n}")


if __name__ == "__main__":
    main()
