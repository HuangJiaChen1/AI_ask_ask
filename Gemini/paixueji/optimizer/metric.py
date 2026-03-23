"""optimizer/metric.py — cosine similarity scoring with LLM synthesis fallback."""
from __future__ import annotations
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trace_schema import TraceObject

SPARSE_THRESHOLD = 20  # chars; below this, synthesize expected response


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def synthesize_expected(critique, exchange, config: dict, client) -> str:
    """LLM-synthesized ideal response from model_response_problem + context."""
    prompt = (
        f"A learning companion for young children gave a response that was criticized: "
        f'"{critique.model_response_problem}". '
        f'The child said: "{exchange.child_response}". '
        "Write one ideal 1–2 sentence response the companion should have given instead."
    )
    try:
        return client.models.generate_content(
            model=config["high_reasoning_model"], contents=[prompt]
        ).text.strip()
    except Exception:
        return ""


def embed_text(text: str, config: dict, client) -> list[float]:
    """Embed text via Vertex AI text-embedding-004."""
    try:
        return client.models.embed_content(
            model=config["embedding_model"], contents=[text]
        ).embeddings[0].values
    except Exception:
        return []


def compute_score(preview: str, expected: str, config: dict, client) -> float:
    """cosine_sim(embed(preview), embed(expected)) → [0.0, 1.0]."""
    if not expected:
        return 0.0
    va = embed_text(preview, config, client)
    vb = embed_text(expected, config, client)
    if not va or not vb:
        return 0.0
    return max(0.0, min(1.0, _cosine_sim(va, vb)))


def compute_batch_score(
    previews: list[str],
    traces: list["TraceObject"],
    config: dict,
    client,
) -> list[float]:
    """Per-trace scoring with synthesize_expected fallback for sparse expected text."""
    scores = []
    for preview, trace in zip(previews, traces):
        expected = trace.critique.model_response_expected or ""
        if len(expected) < SPARSE_THRESHOLD:
            expected = synthesize_expected(trace.critique, trace.exchange, config, client)
        scores.append(compute_score(preview, expected, config, client))
    return scores
