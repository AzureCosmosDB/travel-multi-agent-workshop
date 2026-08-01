"""
Reference-free quality signal (ADR-0010 §5.1, spike B9).

    from src.app.engine import quality

    ex = quality.QualityExample(agent="find_places",
                                question="hotels in Paris",
                                response="Try Hotel Le Bristol and Hotel Lutetia ...")
    quality.deterministic_judge(ex)              # cheap, offline baseline
    judge = quality.build_llm_judge(invoke)      # reference-free LLM judge (model injected)
    quality.calibrate(judge, labeled_dataset)    # agreement vs human labels

All judges return the pluggable `EvaluationResult` primitive. Add an agent rubric by
registering it in `rubrics.py`.
"""

from __future__ import annotations

# Import rubrics so per-agent rubrics register on import.
from . import rubrics  # noqa: F401
from .rubrics import RUBRICS, QualityRubric, get_rubric  # noqa: F401
from .judge import (  # noqa: F401
    EvaluationResult,
    QualityExample,
    QualityJudge,
    build_llm_judge,
    deterministic_judge,
)
from .calibration import LabeledExample, calibrate  # noqa: F401
