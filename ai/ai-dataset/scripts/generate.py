"""
Generate synthetic helpdesk tickets via Qwen (or any OpenAI-compatible LLM).

Iterates over a (category × persona × tone × length) grid; each combination produces
one API call returning N samples. Output is appended to data/raw/<run_id>/samples.jsonl
and is resumable — re-running the same run_id skips already-generated combinations.

Configuration is via environment variables (.env):
    OPENAI_BASE_URL   — provider endpoint (e.g. http://localhost:11434/v1 for Ollama,
                        https://dashscope-intl.aliyuncs.com/compatible-mode/v1 for DashScope)
    OPENAI_API_KEY    — API key (для Ollama любая строка, например 'ollama')
    QWEN_MODEL        — model id (qwen2.5-72b-instruct, qwen-max, qwen3-32b ...)

Usage:
    python scripts/generate.py --run-id v3 --samples-per-combo 2 --concurrency 4
    python scripts/generate.py --run-id v3 --dry-run
    python scripts/generate.py --run-id v3 --model qwen2.5-32b-instruct
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import random
import sys
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI, RateLimitError
from pydantic import ValidationError

from schemas.sample import GenerationBatch, Sample, category_to_department
from scripts._common import (
    ROOT,
    append_jsonl,
    category_title,
    load_prompt,
    load_seed_examples,
    load_taxonomy,
    read_jsonl,
    render_fewshot_block,
)

DEFAULT_MODEL = "qwen2.5-72b-instruct"

CATEGORIES = [
    "it_hardware",
    "it_software_install", "it_software_error",
    "it_access_grant", "it_access_reset",
    "it_network",
    "hr_payroll", "hr_leave", "hr_policy", "hr_onboarding",
    "finance_invoice", "finance_expense", "finance_report",
    "other",
]

PERSONAS = ["бухгалтер", "инженер", "hr_специалист", "новичок", "удалёнщик", "руководитель"]
TONES = ["спокойный", "раздражённый", "паникующий", "формальный"]
LENGTHS = ["короткий", "средний", "длинный"]

CLEANLINESS_GUIDANCE = {
    "messy": (
        "Data style for this batch: messy. User messages should often be short, vague, "
        "imperfect, emotional, typo-prone, or missing key details. Avoid clean textbook cases."
    ),
    "normal": (
        "Data style for this batch: normal. Mix concise real workplace messages with some "
        "missing details and natural follow-up clarification."
    ),
    "formal": (
        "Data style for this batch: formal. User may be polite and structured, but still "
        "avoid perfect legalistic wording and over-complete details in every sample."
    ),
}


# JSON schema description appended to the system prompt — Qwen uses prompt-driven
# structured output (JSON mode), Pydantic validates afterwards.
SCHEMA_HINT = """
ВАЖНО: верни строго JSON по следующей схеме, без какого-либо текста до или после:

{
  "samples": [
    {
      "conversation": [
        {"role": "user" | "agent", "text": "string"}
      ],
      "ticket": {
        "title": "string (≤120 chars)",
        "body": "string",
        "steps_tried": "string или null"
      },
      "labels": {
        "department": "IT" | "HR" | "finance" | "other",
        "category": "<один из id из таксономии>",
        "priority": "критический" | "высокий" | "средний" | "низкий"
      }
    }
  ]
}

В массиве `samples` должно быть ровно столько элементов, сколько запрошено в user-сообщении.
"""
SCHEMA_HINT += """

Hard constraints:
- Return exactly N samples, where N is requested in the user message.
- Every conversation must contain at least 2 messages.
- Every conversation must start with {"role": "user", ...}.
- Every conversation must include at least one {"role": "agent", ...}.
- Roles must alternate user/agent.
- Do not return a one-message conversation.
- Do not make every user polite, precise, and fully informed.
- Many user messages should be vague, incomplete, emotional, typo-prone, or missing details.
- The agent should be helpful but brief; avoid overly warm, perfect, scripted support language.
- For short samples, it is okay if the agent asks one clarifying question or only confirms ticket creation.
- Do not over-specify exact sums, dates, systems, invoice numbers, or model names unless it helps the scenario.

Minimal valid shape for N=1:
{
  "samples": [
    {
      "conversation": [
        {"role": "user", "text": "User problem"},
        {"role": "agent", "text": "Agent clarification or ticket creation"}
      ],
      "ticket": {"title": "Short title", "body": "Ticket body", "steps_tried": null},
      "labels": {"department": "IT", "category": "it_hardware", "priority": "низкий"}
    }
  ]
}
"""


class BatchShapeError(ValueError):
    pass


def validate_batch_shape(batch: GenerationBatch, *, expected_samples: int) -> None:
    if len(batch.samples) != expected_samples:
        raise BatchShapeError(
            f"samples must contain exactly {expected_samples} item(s), got {len(batch.samples)}"
        )


def taxonomy_item(taxonomy: dict[str, Any], category_id: str) -> tuple[str, dict[str, Any]]:
    for dept, items in taxonomy["departments"].items():
        for item in items:
            if item["id"] == category_id:
                return dept, item
    for item in taxonomy["other"]:
        if item["id"] == category_id:
            return "other", item
    raise KeyError(category_id)


def render_target_taxonomy_block(taxonomy: dict[str, Any], category_id: str) -> str:
    dept, item = taxonomy_item(taxonomy, category_id)
    return "\n".join(
        [
            "Target label for this request:",
            f"- department: {dept}",
            f"- category: {item['id']} — {item['title']}",
            f"- category description: {item['description']}",
            "",
            "Allowed departments: IT, HR, finance, other",
            "Allowed categories: " + ", ".join(CATEGORIES),
            "",
            "Priority calibration:",
            taxonomy["priority_calibration"].strip(),
        ]
    )


def validate_sample_semantics(sample: Sample, *, expected_category: str) -> None:
    if sample.labels.category != expected_category:
        raise ValueError(
            f"category {sample.labels.category!r} does not match requested {expected_category!r}"
        )
    expected_department = category_to_department(sample.labels.category)
    if sample.labels.department != expected_department:
        raise ValueError(
            f"department {sample.labels.department!r} does not match category "
            f"{sample.labels.category!r}; expected {expected_department!r}"
        )
    expected_role = "user"
    has_agent = False
    for message in sample.conversation:
        if message.role != expected_role:
            raise ValueError("conversation roles must alternate and start with user")
        has_agent = has_agent or message.role == "agent"
        expected_role = "agent" if expected_role == "user" else "user"
    if not has_agent:
        raise ValueError("conversation must include an agent message")


def parse_generation_batch(
    data: Any, *, expected_samples: int, expected_category: str
) -> tuple[GenerationBatch, list[str]]:
    issues: list[str] = []
    raw_samples = data.get("samples") if isinstance(data, dict) else None
    if not isinstance(raw_samples, list):
        raise BatchShapeError("response must be an object with a samples array")

    valid: list[Sample] = []
    for index, raw_sample in enumerate(raw_samples):
        try:
            sample = Sample.model_validate(raw_sample)
            validate_sample_semantics(sample, expected_category=expected_category)
            valid.append(sample)
        except (ValidationError, ValueError) as exc:
            issues.append(f"samples.{index}: {exc!r}")

    if not valid:
        raise BatchShapeError("; ".join(issues) or "no valid samples")
    if len(valid) > expected_samples:
        issues.append(f"trimmed {len(valid) - expected_samples} extra valid sample(s)")
        valid = valid[:expected_samples]
    if len(valid) < expected_samples:
        issues.append(f"accepted partial batch: expected {expected_samples}, got {len(valid)}")

    return GenerationBatch(samples=valid), issues


def build_system_prompt(category: str) -> str:
    taxonomy = load_taxonomy()
    examples = load_seed_examples()
    template = load_prompt("generator.md")
    base = (
        template.split("# User", 1)[0]
        .replace("{TAXONOMY_BLOCK}", render_target_taxonomy_block(taxonomy, category))
        .replace("{FEWSHOT_BLOCK}", render_fewshot_block(examples))
    )
    return base.strip() + "\n\n" + SCHEMA_HINT.strip()


def build_user_message(
    *, category: str, persona: str, tone: str, length: str, n: int, cleanliness: str
) -> str:
    taxonomy = load_taxonomy()
    template = load_prompt("generator.md")
    user_part = template.split("# User", 1)[1]
    rendered = (
        user_part
        .replace("{N}", str(n))
        .replace("{category}", category)
        .replace("{category_title}", category_title(taxonomy, category))
        .replace("{persona}", persona)
        .replace("{tone}", tone)
        .replace("{length}", length)
    )
    return rendered.strip() + "\n\n" + CLEANLINESS_GUIDANCE[cleanliness]


def combo_key(category: str, persona: str, tone: str, length: str) -> str:
    return f"{category}|{persona}|{tone}|{length}"


def build_grid() -> list[tuple[str, str, str, str]]:
    return list(itertools.product(CATEGORIES, PERSONAS, TONES, LENGTHS))


def combo_cleanliness(key: str, mode: str) -> str:
    if mode != "mixed":
        return mode
    levels = ["messy", "normal", "formal"]
    return levels[sum(ord(ch) for ch in key) % len(levels)]


def limit_combos(
    pending: list[tuple[str, str, str, str]], *, limit: int | None, strategy: str
) -> list[tuple[str, str, str, str]]:
    if limit is None or len(pending) <= limit:
        return pending
    if strategy == "simple":
        return pending[:limit]

    by_category: dict[str, list[tuple[str, str, str, str]]] = {category: [] for category in CATEGORIES}
    for combo in pending:
        by_category[combo[0]].append(combo)

    selected: list[tuple[str, str, str, str]] = []
    while len(selected) < limit:
        added = False
        for category in CATEGORIES:
            items = by_category.get(category) or []
            if not items:
                continue
            selected.append(items.pop(0))
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break
    return selected


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


async def generate_one(
    client: AsyncOpenAI,
    *,
    model: str,
    temperature: float,
    system_prompt: str,
    category: str,
    persona: str,
    tone: str,
    length: str,
    cleanliness: str,
    n: int,
    semaphore: asyncio.Semaphore,
    request_delay: float = 0.0,
    max_retries: int = 2,
    rate_limit_delay: float = 60.0,
) -> tuple[GenerationBatch | None, dict[str, Any]]:
    """Returns (batch, usage_metadata). batch is None on failure."""
    user_message = build_user_message(
        category=category, persona=persona, tone=tone, length=length, n=n, cleanliness=cleanliness
    )

    async with semaphore:
        last_err: str | None = None
        for attempt in range(max_retries + 1):
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ]
                if last_err:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your previous answer was invalid and was rejected by the validator.\n"
                                f"Validator error: {last_err}\n\n"
                                "Return a corrected JSON object only. Keep exactly the requested number "
                                "of samples. Every conversation must have at least two alternating "
                                "messages and include an agent reply."
                            ),
                        }
                    )
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    max_tokens=8000,
                )
                text = response.choices[0].message.content or ""
                data = json.loads(text)
                batch, issues = parse_generation_batch(
                    data, expected_samples=n, expected_category=category
                )
                usage_obj = response.usage
                usage = {
                    "input_tokens": getattr(usage_obj, "prompt_tokens", 0) if usage_obj else 0,
                    "output_tokens": getattr(usage_obj, "completion_tokens", 0) if usage_obj else 0,
                    "attempts": attempt + 1,
                }
                if issues:
                    usage["validation_issues"] = issues[:5]
                if request_delay > 0:
                    await asyncio.sleep(request_delay)
                return batch, usage
            except (json.JSONDecodeError, ValidationError, BatchShapeError) as exc:
                last_err = f"parse/validate: {exc!r}"
                continue
            except RateLimitError as exc:
                last_err = repr(exc)
                if attempt < max_retries:
                    await asyncio.sleep(rate_limit_delay * (attempt + 1))
                    continue
                break
            except Exception as exc:
                last_err = repr(exc)
                break
        return None, {"error": last_err}


async def run(args: argparse.Namespace) -> None:
    grid = build_grid()
    run_dir = ROOT / "data" / "raw" / args.run_id
    samples_path = run_dir / "samples.jsonl"
    state_path = run_dir / "state.jsonl"
    manifest_path = run_dir / "manifest.json"

    completed_keys: set[str] = {
        rec["combo_key"] for rec in read_jsonl(state_path) if rec.get("status") == "ok"
    }

    pending = [combo for combo in grid if combo_key(*combo) not in completed_keys]
    if not args.no_shuffle_grid:
        random.Random(args.grid_seed).shuffle(pending)
    pending = limit_combos(pending, limit=args.limit, strategy=args.limit_strategy)
    print(f"grid size: {len(grid)} combos | already done: {len(completed_keys)} | pending: {len(pending)}")

    if args.dry_run:
        for combo in pending[:20]:
            print("  ", combo_key(*combo))
        if len(pending) > 20:
            print(f"  ... and {len(pending) - 20} more")
        return

    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not base_url:
        print("ERROR: OPENAI_BASE_URL not set in environment", file=sys.stderr)
        sys.exit(1)
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set (для Ollama подойдёт любая строка)", file=sys.stderr)
        sys.exit(1)

    model = args.model or os.environ.get("QWEN_MODEL") or DEFAULT_MODEL

    run_dir.mkdir(parents=True, exist_ok=True)
    if not manifest_path.exists():
        manifest_path.write_text(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "model": model,
                    "base_url": base_url,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "samples_per_combo": args.samples_per_combo,
                    "grid_size": len(grid),
                    "concurrency": args.concurrency,
                    "temperature": args.temperature,
                    "limit": args.limit,
                    "limit_strategy": args.limit_strategy,
                    "grid_seed": args.grid_seed,
                    "cleanliness": args.cleanliness,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    system_prompts = {category: build_system_prompt(category) for category in CATEGORIES}
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    semaphore = asyncio.Semaphore(args.concurrency)

    total_in = total_out = 0
    ok = err = completed = 0
    started = monotonic()

    async def worker(combo: tuple[str, str, str, str]) -> None:
        nonlocal ok, err, completed, total_in, total_out
        category, persona, tone, length = combo
        key = combo_key(*combo)
        cleanliness = combo_cleanliness(key, args.cleanliness)
        batch, usage = await generate_one(
            client,
            model=model,
            temperature=args.temperature,
            system_prompt=system_prompts[category],
            category=category,
            persona=persona,
            tone=tone,
            length=length,
            cleanliness=cleanliness,
            n=args.samples_per_combo,
            semaphore=semaphore,
            request_delay=args.request_delay,
            max_retries=args.max_retries,
            rate_limit_delay=args.rate_limit_delay,
        )

        if batch is None:
            append_jsonl(state_path, {"combo_key": key, "status": "error", **usage})
            err += 1
            completed += 1
            print(f"  [ERR] {key}: {usage.get('error')}")
            if completed % args.progress_every == 0:
                elapsed = monotonic() - started
                avg = elapsed / max(completed, 1)
                eta = avg * max(len(pending) - completed, 0)
                print(
                    f"  [{completed}/{len(pending)}] ok={ok} err={err} "
                    f"avg={avg:.1f}s eta={format_duration(eta)} "
                    f"in={total_in:,} out={total_out:,} tokens"
                )
            return

        for sample in batch.samples:
            append_jsonl(
                samples_path,
                {
                    "combo": {
                        "category": category,
                        "persona": persona,
                        "tone": tone,
                        "length": length,
                        "cleanliness": cleanliness,
                    },
                    "sample": json.loads(sample.model_dump_json()),
                },
            )

        append_jsonl(
            state_path,
            {
                "combo_key": key,
                "status": "ok",
                "n_samples": len(batch.samples),
                "cleanliness": cleanliness,
                **usage,
            },
        )
        total_in += usage.get("input_tokens", 0) or 0
        total_out += usage.get("output_tokens", 0) or 0
        ok += 1
        completed += 1
        if completed % args.progress_every == 0:
            elapsed = monotonic() - started
            avg = elapsed / max(completed, 1)
            eta = avg * max(len(pending) - completed, 0)
            print(
                f"  [{completed}/{len(pending)}] ok={ok} err={err} "
                f"avg={avg:.1f}s eta={format_duration(eta)} "
                f"in={total_in:,} out={total_out:,} tokens"
            )

    await asyncio.gather(*(worker(combo) for combo in pending))

    print(f"\nDone. ok={ok}, err={err}")
    print(f"Samples written to: {samples_path}")
    print(f"Run state:          {state_path}")
    print(f"Total tokens:       in={total_in:,} out={total_out:,}")


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Generate synthetic helpdesk tickets via Qwen / OpenAI-compatible LLM.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--samples-per-combo", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--request-delay", type=float, default=0.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--rate-limit-delay", type=float, default=60.0)
    parser.add_argument("--model", default=None, help="Override QWEN_MODEL env var.")
    parser.add_argument("--limit", type=int, default=None, help="Generate only the first N pending combos.")
    parser.add_argument(
        "--limit-strategy",
        choices=["balanced", "simple"],
        default="balanced",
        help="How to choose combos when --limit is set.",
    )
    parser.add_argument("--progress-every", type=int, default=10, help="Print progress after every N successful combos.")
    parser.add_argument("--grid-seed", type=int, default=42, help="Seed for deterministic combo shuffling.")
    parser.add_argument("--no-shuffle-grid", action="store_true", help="Keep the original category/persona/tone/length order.")
    parser.add_argument(
        "--cleanliness",
        choices=["mixed", "messy", "normal", "formal"],
        default="mixed",
        help="Controls how clean or messy generated user messages should be.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
