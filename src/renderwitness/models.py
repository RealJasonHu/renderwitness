"""Validated data models shared by RenderWitness modules."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RenderWitnessModel(BaseModel):
    """Base model with conservative parsing defaults."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Severity(StrEnum):
    """Impact level assigned to a visual finding."""

    IGNORE = "ignore"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class Verdict(StrEnum):
    """Top-level review recommendation."""

    PASS = "pass"
    REVIEW = "review"
    FAIL = "fail"


class BoundingBox(RenderWitnessModel):
    """Pixel-space rectangle, using an exclusive right and bottom edge."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


def _rectangle_union_area(boxes: list[BoundingBox]) -> int:
    """Count overlapping exclusions exactly without allocating a pixel canvas."""
    edges = sorted({edge for box in boxes for edge in (box.x, box.right)})
    area = 0
    for left, right in zip(edges, edges[1:], strict=False):
        intervals = sorted(
            (box.y, box.bottom) for box in boxes if box.x < right and box.right > left
        )
        height = 0
        end = 0
        for start, bottom in intervals:
            height += max(0, bottom - max(start, end))
            end = max(end, bottom)
        area += (right - left) * height
    return area


class DiffRegion(RenderWitnessModel):
    """A connected region of pixels that differs between two images."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    bbox: BoundingBox
    area: int = Field(gt=0)
    changed_pixels: int = Field(gt=0)
    pixel_ratio: float = Field(ge=0.0, le=1.0)
    mean_delta: float = Field(ge=0.0, le=255.0)
    max_delta: int = Field(ge=0, le=255)

    @model_validator(mode="after")
    def validate_pixel_counts(self) -> DiffRegion:
        expected_area = self.bbox.width * self.bbox.height
        if self.area != expected_area:
            raise ValueError("area must equal bbox.width * bbox.height")
        if self.changed_pixels > self.area:
            raise ValueError("changed_pixels cannot exceed area")
        if not math.isclose(
            self.pixel_ratio,
            self.changed_pixels / self.area,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise ValueError("pixel_ratio must equal changed_pixels / area")
        return self


class ImageInfo(RenderWitnessModel):
    """Non-pixel metadata captured for an input image."""

    path: str = Field(min_length=1, max_length=4096)
    filename: str = Field(min_length=1, max_length=512)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mode: str = Field(min_length=1, max_length=32)
    format: str = Field(min_length=1, max_length=32)
    byte_size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ComparisonResult(RenderWitnessModel):
    """Deterministic output from the pixel comparison stage."""

    baseline: ImageInfo
    candidate: ImageInfo
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    threshold: int = Field(ge=0, le=255)
    min_region_area: int = Field(default=16, ge=1)
    max_regions: int = Field(default=20, ge=1, le=200)
    grouping_distance: int = Field(default=8, ge=0, le=128)
    region_padding: int = Field(default=24, ge=0, le=256)
    changed_pixels: int = Field(ge=0)
    total_pixels: int = Field(gt=0)
    ignored_regions: list[BoundingBox] = Field(default_factory=list, max_length=200)
    ignored_pixels: int = Field(default=0, ge=0)
    change_ratio: float = Field(ge=0.0, le=1.0)
    identical: bool
    regions: list[DiffRegion] = Field(default_factory=list, max_length=200)
    algorithm_version: str = Field(default="grid-roi-v1", min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_totals(self) -> ComparisonResult:
        expected_total = self.width * self.height
        if self.total_pixels != expected_total:
            raise ValueError("total_pixels must equal width * height")
        if self.ignored_pixels >= self.total_pixels:
            raise ValueError("ignored regions must leave at least one pixel to compare")
        if self.changed_pixels > self.total_pixels - self.ignored_pixels:
            raise ValueError("changed_pixels cannot exceed total_pixels minus ignored_pixels")
        if self.identical != (self.changed_pixels == 0):
            raise ValueError("identical must match whether changed_pixels is zero")
        if not math.isclose(
            self.change_ratio,
            self.changed_pixels / (self.total_pixels - self.ignored_pixels),
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise ValueError("change_ratio must equal changed_pixels / non-ignored pixels")
        if (self.baseline.width, self.baseline.height) != (self.width, self.height):
            raise ValueError("baseline dimensions must match comparison dimensions")
        if (self.candidate.width, self.candidate.height) != (self.width, self.height):
            raise ValueError("candidate dimensions must match comparison dimensions")
        region_ids: set[str] = set()
        for box in self.ignored_regions:
            if box.right > self.width or box.bottom > self.height:
                raise ValueError("ignored region exceeds comparison dimensions")
        if self.ignored_pixels != _rectangle_union_area(self.ignored_regions):
            raise ValueError("ignored_pixels must equal the union area of ignored_regions")
        for region in self.regions:
            if region.id in region_ids:
                raise ValueError(f"duplicate region id: {region.id}")
            region_ids.add(region.id)
            if region.bbox.right > self.width or region.bbox.bottom > self.height:
                raise ValueError(f"region '{region.id}' exceeds comparison dimensions")
        return self


class Finding(RenderWitnessModel):
    """A provider's structured explanation of one visual issue."""

    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    region_id: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    category: str = Field(min_length=1, max_length=80)
    severity: Severity
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)
    suggestion: str | None = Field(default=None, max_length=1000)

    @field_validator("category", "title", "description", "suggestion")
    @classmethod
    def reject_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("text fields cannot contain NUL characters")
        return value


class ProviderPayload(RenderWitnessModel):
    """Provider-authored fields accepted from a remote model response."""

    summary: str = Field(min_length=1, max_length=4000)
    verdict: Verdict
    findings: list[Finding] = Field(default_factory=list, max_length=100)


class ProviderResult(RenderWitnessModel):
    """Normalized provider output, including provider provenance."""

    provider: str = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    prompt_version: str | None = Field(default=None, min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=4000)
    verdict: Verdict
    findings: list[Finding] = Field(default_factory=list, max_length=100)


def _now_utc() -> datetime:
    return datetime.now(UTC)


class AnalysisResult(RenderWitnessModel):
    """Complete comparison and semantic-analysis result."""

    comparison: ComparisonResult
    provider: str = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    prompt_version: str | None = Field(default=None, min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=4000)
    verdict: Verdict
    findings: list[Finding] = Field(default_factory=list, max_length=100)
    analysis_ms: float = Field(default=0.0, ge=0.0)
    generated_at: datetime = Field(default_factory=_now_utc)

    @field_validator("generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value
