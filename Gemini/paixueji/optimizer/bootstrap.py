"""optimizer/bootstrap.py — golden example library (DSPy-B few-shot injection)."""
from __future__ import annotations
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from trace_schema import TraceObject

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
GOLDEN_THRESHOLD = 0.90
MAX_EXAMPLES = 30


class GoldenExampleContext(BaseModel):
    age: int
    object_name: str
    child_response: str
    conversation_history_tail: list[dict]


class GoldenExample(BaseModel):
    id: str
    prompt_name: str
    context: GoldenExampleContext
    response: str
    score: float
    trace_id: str
    added_at: str


def _load(prompt_name: str) -> list[GoldenExample]:
    path = EXAMPLES_DIR / f"{prompt_name}.json"
    if not path.exists():
        return []
    try:
        return [GoldenExample.model_validate(d)
                for d in json.loads(path.read_text(encoding="utf-8"))]
    except Exception:
        return []


def _save(prompt_name: str, examples: list[GoldenExample]) -> None:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    (EXAMPLES_DIR / f"{prompt_name}.json").write_text(
        json.dumps([e.model_dump() for e in examples], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_golden_example(
    prompt_name: str, trace: "TraceObject", preview: str, score: float
) -> None:
    """Save if score >= GOLDEN_THRESHOLD. Evict lowest-scoring if MAX_EXAMPLES exceeded."""
    if score < GOLDEN_THRESHOLD:
        return
    tail = (trace.conversation_history or [])[-3:]
    examples = _load(prompt_name)
    examples.append(GoldenExample(
        id=str(uuid.uuid4()),
        prompt_name=prompt_name,
        context=GoldenExampleContext(
            age=trace.age or 0,
            object_name=trace.object_name,
            child_response=trace.exchange.child_response,
            conversation_history_tail=tail,
        ),
        response=preview,
        score=score,
        trace_id=trace.trace_id,
        added_at=datetime.utcnow().isoformat(),
    ))
    if len(examples) > MAX_EXAMPLES:
        examples = sorted(examples, key=lambda e: e.score, reverse=True)[:MAX_EXAMPLES]
    _save(prompt_name, examples)


def get_best_examples(prompt_name: str, k: int = 3) -> list[GoldenExample]:
    """Top-K examples sorted by score descending. Returns [] if none exist."""
    return sorted(_load(prompt_name), key=lambda e: e.score, reverse=True)[:k]


def inject_examples(prompt_text: str, examples: list[GoldenExample]) -> str:
    """Inject into {few_shot_examples} placeholder or append a new clause section."""
    if not examples:
        return prompt_text
    block = "\n".join(
        f'Child said "{e.context.child_response}" \u2192 Good response: "{e.response}"'
        for e in examples
    )
    if "{few_shot_examples}" in prompt_text:
        return prompt_text.replace("{few_shot_examples}", block)
    return prompt_text + f"\n\n## [CLAUSE: few_shot_examples]\n{block}\n"
