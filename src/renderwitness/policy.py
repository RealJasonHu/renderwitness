"""Explicit CI decisions, kept separate from provider recommendations."""

from __future__ import annotations

from pydantic import Field

from .models import AnalysisResult, RenderWitnessModel, Severity, Verdict

_RANK = {Severity.IGNORE: 0, Severity.MINOR: 1, Severity.MAJOR: 2, Severity.CRITICAL: 3}


class GatePolicy(RenderWitnessModel):
    """Opt-in thresholds; an empty policy never fails a completed comparison."""

    max_change_ratio: float | None = Field(default=None, ge=0, le=1)
    fail_on_severity: Severity | None = None
    min_confidence: float = Field(default=0.8, ge=0, le=1)
    fail_on_review: bool = False


class GateResult(RenderWitnessModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    policy: GatePolicy


def evaluate_policy(result: AnalysisResult, policy: GatePolicy) -> GateResult:
    """Evaluate measured change budget and optional provider-authored findings."""
    reasons: list[str] = []
    if (
        policy.max_change_ratio is not None
        and result.comparison.change_ratio > policy.max_change_ratio
    ):
        reasons.append(
            f"Changed-pixel ratio {result.comparison.change_ratio:.6%} exceeds "
            f"budget {policy.max_change_ratio:.6%}."
        )
    if policy.fail_on_severity is not None:
        for finding in result.findings:
            if (
                _RANK[finding.severity] >= _RANK[policy.fail_on_severity]
                and finding.confidence >= policy.min_confidence
            ):
                reasons.append(
                    f"Finding {finding.id}: {finding.severity.value} at "
                    f"{finding.confidence:.0%} confidence meets the severity gate."
                )
    if policy.fail_on_review and result.verdict in {Verdict.REVIEW, Verdict.FAIL}:
        reasons.append(f"Provider verdict '{result.verdict.value}' requires review.")
    return GateResult(passed=not reasons, reasons=reasons, policy=policy)
