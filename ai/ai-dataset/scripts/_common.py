from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_taxonomy() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "taxonomy.yaml").read_text(encoding="utf-8"))


def render_taxonomy_block(taxonomy: dict[str, Any]) -> str:
    """Compact human-readable rendering of taxonomy for the system prompt."""
    lines: list[str] = []
    lines.append("Departments and categories:")
    for dept, items in taxonomy["departments"].items():
        lines.append(f"\n[{dept}]")
        for item in items:
            lines.append(f"  - {item['id']} — {item['title']}: {item['description']}")
    lines.append("\n[other]")
    for item in taxonomy["other"]:
        lines.append(f"  - {item['id']} — {item['title']}: {item['description']}")
    lines.append("\nPriorities (business-impact calibration):")
    lines.append(taxonomy["priority_calibration"].strip())
    return "\n".join(lines)


def load_seed_examples() -> list[dict[str, Any]]:
    path = ROOT / "data" / "seed" / "examples.jsonl"
    examples = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    limit = int(os.environ.get("AI_DATASET_SEED_EXAMPLES_LIMIT", "8"))
    if limit <= 0 or len(examples) <= limit:
        return examples

    by_category: dict[str, list[dict[str, Any]]] = {}
    for sample in examples:
        category = sample.get("labels", {}).get("category", "")
        by_category.setdefault(category, []).append(sample)

    category_order = [
        "it_hardware",
        "it_software_install",
        "it_software_error",
        "it_access_grant",
        "it_access_reset",
        "it_network",
        "hr_payroll",
        "hr_leave",
        "hr_policy",
        "hr_onboarding",
        "finance_invoice",
        "finance_expense",
        "finance_report",
        "other",
    ]
    picked: list[dict[str, Any]] = []
    seen: set[int] = set()
    for category in category_order:
        items = by_category.get(category, [])
        if not items:
            continue
        picked.append(items[0])
        seen.add(id(items[0]))
        if len(picked) >= limit:
            return picked

    for sample in examples:
        if id(sample) in seen:
            continue
        picked.append(sample)
        if len(picked) >= limit:
            break
    return picked


def render_fewshot_block(examples: Iterable[dict[str, Any]]) -> str:
    """Render seed examples as a JSON code block — keeps the schema visible."""
    payload = json.dumps(list(examples), ensure_ascii=False, separators=(",", ":"))
    return f"```json\n{payload}\n```"


def load_prompt(name: str) -> str:
    return (ROOT / "prompts" / name).read_text(encoding="utf-8")


def category_title(taxonomy: dict[str, Any], category_id: str) -> str:
    for items in taxonomy["departments"].values():
        for item in items:
            if item["id"] == category_id:
                return item["title"]
    for item in taxonomy["other"]:
        if item["id"] == category_id:
            return item["title"]
    raise KeyError(category_id)


def department_for_category(taxonomy: dict[str, Any], category_id: str) -> str:
    for dept, items in taxonomy["departments"].items():
        for item in items:
            if item["id"] == category_id:
                return dept
    for item in taxonomy["other"]:
        if item["id"] == category_id:
            return "other"
    raise KeyError(category_id)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False))
        f.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
