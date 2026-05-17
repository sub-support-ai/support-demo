"""
LLM-as-judge validation: проверяет каждый сгенерированный семпл на соответствие
таксономии. Использует Qwen (или любой OpenAI-совместимый LLM) в JSON-mode.

Usage:
    python scripts/judge.py --run-id v3 --concurrency 4

Inputs:  data/raw/<run_id>/samples.jsonl
Outputs: data/processed/<run_id>/judged.jsonl
         data/processed/<run_id>/rejected.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from openai import AsyncOpenAI, RateLimitError
from pydantic import ValidationError

from schemas.sample import JudgeVerdict
from scripts._common import (
    ROOT,
    append_jsonl,
    load_prompt,
    load_taxonomy,
    read_jsonl,
    render_taxonomy_block,
)

DEFAULT_MODEL = "qwen2.5-72b-instruct"


JUDGE_SCHEMA_HINT = """
ВАЖНО: верни строго JSON без какого-либо текста до или после:

{
  "valid": true | false,
  "label_match": true | false,
  "issues": ["краткая формулировка замечания", ...],
  "corrected_labels": null | {
    "department": "IT" | "HR" | "finance" | "other",
    "category": "<один из id из таксономии>",
    "priority": "критический" | "высокий" | "средний" | "низкий"
  }
}

Если label_match=true — corrected_labels должен быть null.
"""


def build_system_prompt() -> str:
    template = load_prompt("judge.md")
    taxonomy = load_taxonomy()
    base = template.split("# User", 1)[0].replace(
        "{TAXONOMY_BLOCK}", render_taxonomy_block(taxonomy)
    )
    return base.strip() + "\n\n" + JUDGE_SCHEMA_HINT.strip()


def build_user_message(sample: dict) -> str:
    template = load_prompt("judge.md")
    user_part = template.split("# User", 1)[1]
    return user_part.replace(
        "{SAMPLE_JSON}", json.dumps(sample, ensure_ascii=False, indent=2)
    )


async def judge_one(
    client: AsyncOpenAI,
    *,
    model: str,
    temperature: float,
    system_prompt: str,
    sample: dict,
    semaphore: asyncio.Semaphore,
    request_delay: float = 0.0,
    max_retries: int = 2,
    rate_limit_delay: float = 60.0,
) -> JudgeVerdict | None:
    async with semaphore:
        last_err: str | None = None
        for _ in range(max_retries + 1):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": build_user_message(sample)},
                    ],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    max_tokens=2000,
                )
                text = response.choices[0].message.content or ""
                data = json.loads(text)
                verdict = JudgeVerdict.model_validate(data)
                if request_delay > 0:
                    await asyncio.sleep(request_delay)
                return verdict
            except (json.JSONDecodeError, ValidationError) as exc:
                last_err = f"parse/validate: {exc!r}"
                continue
            except RateLimitError as exc:
                last_err = repr(exc)
                if _ < max_retries:
                    await asyncio.sleep(rate_limit_delay * (_ + 1))
                    continue
                break
            except Exception as exc:
                last_err = repr(exc)
                break
        print(f"  [judge error] {last_err}", file=sys.stderr)
        return None


async def run(args: argparse.Namespace) -> None:
    raw_path = ROOT / "data" / "raw" / args.run_id / "samples.jsonl"
    out_dir = ROOT / "data" / "processed" / args.run_id
    judged_path = out_dir / "judged.jsonl"
    rejected_path = out_dir / "rejected.jsonl"

    if not raw_path.exists():
        print(f"ERROR: {raw_path} not found", file=sys.stderr)
        sys.exit(1)

    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not base_url or not api_key:
        print("ERROR: OPENAI_BASE_URL / OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    model = args.model or os.environ.get("QWEN_MODEL") or DEFAULT_MODEL

    records = read_jsonl(raw_path)
    print(f"loaded {len(records)} samples from {raw_path}")

    # Каждый прогон judge — полный пересмотр входа. Не накапливаем поверх предыдущего.
    out_dir.mkdir(parents=True, exist_ok=True)
    judged_path.unlink(missing_ok=True)
    rejected_path.unlink(missing_ok=True)

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    semaphore = asyncio.Semaphore(args.concurrency)
    system_prompt = build_system_prompt()

    accepted = relabeled = rejected = 0

    async def worker(record: dict) -> None:
        nonlocal accepted, relabeled, rejected
        verdict = await judge_one(
            client,
            model=model,
            temperature=args.temperature,
            system_prompt=system_prompt,
            sample=record["sample"],
            semaphore=semaphore,
            request_delay=args.request_delay,
            max_retries=args.max_retries,
            rate_limit_delay=args.rate_limit_delay,
        )
        if verdict is None:
            append_jsonl(rejected_path, {**record, "rejection_reason": "judge_error"})
            rejected += 1
            return

        if not verdict.valid:
            append_jsonl(
                rejected_path,
                {**record, "verdict": json.loads(verdict.model_dump_json())},
            )
            rejected += 1
            return

        out = dict(record)
        if not verdict.label_match and verdict.corrected_labels is not None:
            out["sample"] = {
                **record["sample"],
                "labels": json.loads(verdict.corrected_labels.model_dump_json()),
            }
            out["original_labels"] = record["sample"]["labels"]
            relabeled += 1
        else:
            accepted += 1

        out["verdict"] = json.loads(verdict.model_dump_json())
        append_jsonl(judged_path, out)

    await asyncio.gather(*(worker(r) for r in records))

    print(f"\naccepted: {accepted}, relabeled: {relabeled}, rejected: {rejected}")
    print(f"judged:   {judged_path}")
    print(f"rejected: {rejected_path}")


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--model", default=None)
    parser.add_argument("--request-delay", type=float, default=0.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--rate-limit-delay", type=float, default=60.0)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
