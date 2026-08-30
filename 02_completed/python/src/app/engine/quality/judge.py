"""
Reference-free quality judge (ADR-0010 §5.1, spike B9).

`EvaluationResult` is the pluggable primitive the whole platform speaks (the guide's §5.1):
any judge — heuristic, this LLM one, or a LangSmith/DeepEval evaluator — maps to it.

Two judges here share the `QualityJudge` shape `(example) -> EvaluationResult`:
  * `DeterministicJudge` — cheap heuristics over the rubric; no LLM, so the engine and its
    tests run offline and calibration has a baseline.
  * `build_llm_judge(invoke)` — the reference-free LLM judge. The model is injected as a
    plain `invoke(system, user) -> str` callable, so this module never imports the app's
    LangChain stack and stays reusable (Travel API and the Fabric notebook alike).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from .rubrics import QualityRubric, get_rubric


@dataclass
class QualityExample:
    """One thing to judge: a response, its agent, and the eliciting context."""
    agent: str
    response: str
    question: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """The platform's pluggable evaluation primitive (§5.1)."""
    agent: str
    dimension: str
    score: float
    passed: bool
    reasoning: str = ""
    scale: tuple = (1, 5)
    source: str = "engine"


QualityJudge = Callable[[QualityExample], EvaluationResult]


# --- deterministic judge (no LLM) -------------------------------------------------

_VAGUE = re.compile(r"\b(some|a few|various|several|places|options|restaurants|hotels)\b", re.I)
_PROPER = re.compile(r"\b([A-Z][a-zA-Z'&]+(?:\s+[A-Z][a-zA-Z'&]+)+)\b")  # multi-word proper nouns
_DAY = re.compile(r"\bday\s*\d", re.I)


def deterministic_judge(example: QualityExample) -> EvaluationResult:
    """Heuristic reference-free score from the agent's rubric — a cheap, stable baseline."""
    r = get_rubric(example.agent)
    text = example.response or ""
    lo, hi = r.scale
    score = lo + (hi - lo) / 2.0            # neutral midpoint
    if len(text.split()) >= 20:
        score += 0.5
    if r.expects_named_entities:
        named = len(set(_PROPER.findall(text)))
        score += min(2.0, 0.7 * named) if named else -1.5
    if r.expects_structure:
        score += 1.0 if _DAY.search(text) else -1.0
    if _VAGUE.search(text) and not _PROPER.search(text):
        score -= 0.5
    score = max(lo, min(hi, score))
    return EvaluationResult(
        agent=example.agent, dimension=r.dimension, score=round(score, 2),
        passed=score >= r.pass_threshold, scale=r.scale, source="deterministic",
        reasoning="heuristic: entity/structure/length signals vs rubric",
    )


# --- reference-free LLM judge -----------------------------------------------------

def _prompt(example: QualityExample, r: QualityRubric) -> tuple[str, str]:
    lo, hi = r.scale
    system = (
        f"You are a strict, reference-free evaluator of a travel assistant's '{r.agent}' agent.\n"
        f"There is NO gold answer — judge the response on its own merits against these criteria:\n"
        + "\n".join(f"  - {c}" for c in r.criteria)
        + f"\n\nReturn ONLY compact JSON: {{\"score\": <int {lo}-{hi}>, \"reasoning\": \"<one sentence>\"}}."
    )
    user = f"USER REQUEST: {example.question}\n\nAGENT RESPONSE:\n{example.response}"
    return system, user


def _parse(raw: str, r: QualityRubric) -> tuple[float, str]:
    lo, hi = r.scale
    try:
        m = re.search(r"\{.*\}", raw, re.S)
        obj = json.loads(m.group(0) if m else raw)
        return max(lo, min(hi, float(obj.get("score", lo)))), str(obj.get("reasoning", ""))[:300]
    except Exception:  # noqa: BLE001
        nums = re.findall(r"[1-5]", raw)
        return (float(nums[0]) if nums else lo), raw[:300]


def build_llm_judge(invoke: Callable[[str, str], str]) -> QualityJudge:
    """Build a reference-free LLM judge from an `invoke(system, user) -> str` callable."""
    def judge(example: QualityExample) -> EvaluationResult:
        r = get_rubric(example.agent)
        system, user = _prompt(example, r)
        score, reasoning = _parse(invoke(system, user), r)
        return EvaluationResult(
            agent=example.agent, dimension=r.dimension, score=score,
            passed=score >= r.pass_threshold, reasoning=reasoning,
            scale=r.scale, source="llm",
        )
    return judge
