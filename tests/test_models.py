from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from renderwitness.models import (
    AnalysisResult,
    BoundingBox,
    ComparisonResult,
    DiffRegion,
    Finding,
    ImageInfo,
    ProviderResult,
)


def image_info(filename: str) -> ImageInfo:
    return ImageInfo(
        path=f"/evidence/{filename}",
        filename=filename,
        width=100,
        height=80,
        mode="RGB",
        format="PNG",
        byte_size=512,
        sha256="a" * 64,
    )


def comparison_result() -> ComparisonResult:
    return ComparisonResult(
        baseline=image_info("baseline.png"),
        candidate=image_info("candidate.png"),
        width=100,
        height=80,
        threshold=24,
        changed_pixels=80,
        total_pixels=8000,
        change_ratio=0.01,
        identical=False,
        regions=[
            DiffRegion(
                id="region-01",
                bbox=BoundingBox(x=10, y=12, width=10, height=10),
                area=100,
                changed_pixels=80,
                pixel_ratio=0.8,
                mean_delta=91.5,
                max_delta=255,
            )
        ],
        algorithm_version="grid-roi-v1",
    )


def test_models_round_trip_without_losing_evidence() -> None:
    comparison = comparison_result()
    provider = ProviderResult(
        provider="demo",
        model="deterministic-rules-v1",
        summary="One meaningful regression.",
        verdict="fail",
        findings=[
            Finding(
                id="finding-01",
                region_id="region-01",
                category="text",
                severity="major",
                title="CTA is clipped",
                description="The final characters are no longer visible.",
                confidence=0.95,
                suggestion="Restore intrinsic sizing.",
            )
        ],
    )
    result = AnalysisResult(
        comparison=comparison,
        provider=provider.provider,
        model=provider.model,
        summary=provider.summary,
        verdict=provider.verdict,
        findings=provider.findings,
        generated_at=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
    )

    restored = AnalysisResult.model_validate_json(result.model_dump_json())

    assert restored == result
    assert restored.comparison.regions[0].bbox == BoundingBox(x=10, y=12, width=10, height=10)
    assert restored.findings[0].region_id == "region-01"


@pytest.mark.parametrize(
    ("factory", "kwargs"),
    [
        (BoundingBox, {"x": -1, "y": 0, "width": 1, "height": 1}),
        (BoundingBox, {"x": 0, "y": 0, "width": 0, "height": 1}),
        (
            Finding,
            {
                "id": "bad-confidence",
                "category": "text",
                "severity": "major",
                "title": "Invalid",
                "description": "Confidence must be calibrated.",
                "confidence": 1.01,
            },
        ),
        (
            Finding,
            {
                "id": "bad-severity",
                "category": "text",
                "severity": "catastrophic",
                "title": "Invalid",
                "description": "Unknown severities must not enter reports.",
                "confidence": 0.5,
            },
        ),
    ],
)
def test_models_reject_values_that_would_corrupt_report_contract(
    factory: type[BoundingBox] | type[Finding], kwargs: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        factory(**kwargs)


def test_schema_is_closed_to_silent_provider_typos() -> None:
    with pytest.raises(ValidationError):
        Finding(
            id="finding-01",
            category="text",
            severity="major",
            title="CTA is clipped",
            description="Visible text is cut off.",
            confidence=0.9,
            confdence=0.1,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("area", 99, "area must equal"),
        ("changed_pixels", 101, "cannot exceed area"),
        ("pixel_ratio", 0.7, "pixel_ratio must equal"),
    ],
)
def test_diff_region_metrics_must_be_internally_consistent(
    field: str, value: object, message: str
) -> None:
    payload = {
        "id": "region-001",
        "bbox": {"x": 10, "y": 12, "width": 10, "height": 10},
        "area": 100,
        "changed_pixels": 80,
        "pixel_ratio": 0.8,
        "mean_delta": 91.5,
        "max_delta": 255,
    }
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        DiffRegion.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("total_pixels",), 7999, "total_pixels must equal"),
        (("changed_pixels",), 8001, "cannot exceed total_pixels"),
        (("identical",), True, "identical must match"),
        (("change_ratio",), 0.5, "change_ratio must equal"),
        (("baseline", "width"), 99, "baseline dimensions"),
        (("candidate", "height"), 79, "candidate dimensions"),
        (("regions", 0, "bbox", "x"), 95, "exceeds comparison dimensions"),
    ],
)
def test_comparison_totals_and_geometry_cannot_contradict_evidence(
    path: tuple[object, ...], value: object, message: str
) -> None:
    payload = comparison_result().model_dump(mode="json")
    target: object = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ValidationError, match=message):
        ComparisonResult.model_validate(payload)


def test_comparison_rejects_duplicate_region_ids() -> None:
    payload = comparison_result().model_dump(mode="json")
    payload["regions"].append(deepcopy(payload["regions"][0]))

    with pytest.raises(ValidationError, match="duplicate region id"):
        ComparisonResult.model_validate(payload)


def test_text_fields_reject_nul_and_timestamp_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="NUL"):
        Finding(
            id="finding-001",
            category="layout\x00override",
            severity="major",
            title="Invalid text",
            description="NUL bytes must not reach HTML.",
            confidence=0.5,
        )

    payload = {
        "comparison": comparison_result().model_dump(mode="json"),
        "provider": "demo",
        "summary": "Summary",
        "verdict": "review",
        "generated_at": datetime(2026, 8, 27, 12, 0),
    }
    with pytest.raises(ValidationError, match="timezone-aware"):
        AnalysisResult.model_validate(payload)
