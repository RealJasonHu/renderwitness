"""Orchestration between deterministic pixel diffing and vision providers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

from .diff import compare_images
from .models import AnalysisResult, BoundingBox, ComparisonResult
from .providers import DemoProvider, ProviderError, VisionProvider


class AnalysisError(RuntimeError):
    """Raised when otherwise valid provider output conflicts with the diff."""


def analyze(
    comparison: ComparisonResult,
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    provider: VisionProvider | None = None,
) -> AnalysisResult:
    """Run a provider and validate its references against comparison ROIs."""

    selected = provider or DemoProvider()
    started_at = perf_counter()
    try:
        provider_result = selected.analyze(
            comparison, Path(baseline_path).expanduser(), Path(candidate_path).expanduser()
        )
    except ProviderError:
        raise
    except Exception as exc:
        # Custom providers should not leak implementation tracebacks through the CLI.
        raise AnalysisError(f"Provider '{selected.name}' failed: {exc}") from exc

    region_ids = {region.id for region in comparison.regions}
    finding_ids: set[str] = set()
    for finding in provider_result.findings:
        if finding.id in finding_ids:
            raise AnalysisError(f"Provider returned duplicate finding id '{finding.id}'")
        finding_ids.add(finding.id)
        if finding.region_id is not None and finding.region_id not in region_ids:
            raise AnalysisError(
                f"Finding '{finding.id}' references unknown region '{finding.region_id}'"
            )

    return AnalysisResult(
        comparison=comparison,
        provider=provider_result.provider,
        model=provider_result.model,
        prompt_version=provider_result.prompt_version,
        summary=provider_result.summary,
        verdict=provider_result.verdict,
        findings=provider_result.findings,
        analysis_ms=(perf_counter() - started_at) * 1000,
    )


def compare_and_analyze(
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    provider: VisionProvider | None = None,
    threshold: int = 24,
    min_region_area: int = 16,
    max_regions: int = 20,
    grouping_distance: int = 8,
    region_padding: int = 24,
    max_image_bytes: int = 25 * 1024 * 1024,
    max_pixels: int = 40_000_000,
    ignore_regions: Sequence[BoundingBox] = (),
) -> AnalysisResult:
    """Convenience API for the complete in-process pipeline."""

    comparison = compare_images(
        baseline_path,
        candidate_path,
        threshold=threshold,
        min_region_area=min_region_area,
        max_regions=max_regions,
        grouping_distance=grouping_distance,
        region_padding=region_padding,
        max_image_bytes=max_image_bytes,
        max_pixels=max_pixels,
        ignore_regions=ignore_regions,
    )
    return analyze(
        comparison,
        baseline_path,
        candidate_path,
        provider=provider,
    )
