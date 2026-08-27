from __future__ import annotations

from pathlib import Path

import pytest

from renderwitness.analyzer import AnalysisError, analyze, compare_and_analyze
from renderwitness.diff import compare_images
from renderwitness.models import Finding, ProviderResult
from renderwitness.providers import ProviderError


class StubProvider:
    name = "stub"

    def __init__(self, result: ProviderResult) -> None:
        self.result = result
        self.paths: tuple[Path, Path] | None = None

    def analyze(
        self, comparison: object, baseline_path: Path, candidate_path: Path
    ) -> ProviderResult:
        self.paths = (baseline_path, candidate_path)
        return self.result


def provider_result(*findings: Finding) -> ProviderResult:
    return ProviderResult(
        provider="stub",
        model="stub-v1",
        summary="Stubbed structured analysis.",
        verdict="review",
        findings=list(findings),
    )


def test_analyze_preserves_comparison_and_provider_provenance(
    image_pair: tuple[Path, Path],
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)
    region_id = comparison.regions[0].id
    stub = StubProvider(
        provider_result(
            Finding(
                id="finding-001",
                region_id=region_id,
                category="layout",
                severity="minor",
                title="Spacing changed",
                description="The card spacing differs visibly.",
                confidence=0.8,
            )
        )
    )

    result = analyze(comparison, baseline, candidate, provider=stub)

    assert result.comparison is comparison
    assert result.provider == "stub"
    assert result.model == "stub-v1"
    assert result.findings[0].region_id == region_id
    assert stub.paths == (baseline, candidate)
    assert result.generated_at.utcoffset() is not None


@pytest.mark.parametrize("failure", ["unknown-region", "duplicate-id"])
def test_analyze_rejects_ungrounded_or_ambiguous_findings(
    image_pair: tuple[Path, Path], failure: str
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)
    first_region = comparison.regions[0].id
    findings = [
        Finding(
            id="finding-001",
            region_id="region-missing" if failure == "unknown-region" else first_region,
            category="layout",
            severity="major",
            title="Grounding check",
            description="This finding exercises analyzer validation.",
            confidence=0.9,
        )
    ]
    if failure == "duplicate-id":
        findings.append(findings[0].model_copy(update={"region_id": comparison.regions[-1].id}))

    with pytest.raises(AnalysisError, match="unknown region|duplicate finding"):
        analyze(
            comparison,
            baseline,
            candidate,
            provider=StubProvider(provider_result(*findings)),
        )


def test_analyze_wraps_unexpected_custom_provider_failures(
    image_pair: tuple[Path, Path],
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)

    class BrokenProvider:
        name = "broken"

        def analyze(self, *args: object) -> ProviderResult:
            raise RuntimeError("decoder crashed")

    with pytest.raises(AnalysisError, match="Provider 'broken' failed: decoder crashed"):
        analyze(comparison, baseline, candidate, provider=BrokenProvider())


def test_analyze_preserves_actionable_provider_errors(
    image_pair: tuple[Path, Path],
) -> None:
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1)

    class ConfigErrorProvider:
        name = "misconfigured"

        def analyze(self, *args: object) -> ProviderResult:
            raise ProviderError("model is required")

    with pytest.raises(ProviderError, match="model is required"):
        analyze(comparison, baseline, candidate, provider=ConfigErrorProvider())


def test_compare_and_analyze_runs_the_public_pipeline(
    image_pair: tuple[Path, Path],
) -> None:
    baseline, candidate = image_pair

    result = compare_and_analyze(
        baseline,
        candidate,
        threshold=8,
        min_region_area=1,
        grouping_distance=0,
    )

    assert result.comparison.threshold == 8
    assert result.provider == "demo"
    assert result.findings
