"""Validated screenshot suites with independent cases and portable CI artifacts."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .analyzer import AnalysisError, analyze
from .diff import ComparisonError, compare_images
from .models import AnalysisResult, BoundingBox, RenderWitnessModel, Verdict
from .policy import GatePolicy, GateResult, evaluate_policy
from .providers import DemoProvider, ProviderError, VisionProvider
from .report import ReportError, _atomic_write, write_report
from .suite_report import write_suite_report


class SuiteError(ValueError):
    """Invalid or unsafe suite configuration."""


class DiffOptions(RenderWitnessModel):
    threshold: int = Field(default=24, ge=0, le=255)
    min_region_area: int = Field(default=16, ge=1)
    max_regions: int = Field(default=20, ge=1, le=200)
    grouping_distance: int = Field(default=8, ge=0, le=128)
    region_padding: int = Field(default=24, ge=0, le=256)
    max_image_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    max_pixels: int = Field(default=40_000_000, ge=1)


class Scenario(RenderWitnessModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    baseline: str = Field(min_length=1, max_length=4096)
    candidate: str = Field(min_length=1, max_length=4096)
    ignore_regions: list[BoundingBox] = Field(default_factory=list, max_length=200)
    diff: DiffOptions = Field(default_factory=DiffOptions)
    policy: GatePolicy = Field(default_factory=GatePolicy)


class SuiteConfig(RenderWitnessModel):
    version: Literal[1] = 1
    name: str = Field(default="Visual regression suite", min_length=1, max_length=200)
    defaults: DiffOptions = Field(default_factory=DiffOptions)
    policy: GatePolicy = Field(default_factory=GatePolicy)
    scenarios: list[Scenario] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_ids(self) -> SuiteConfig:
        ids = [scenario.id.casefold() for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("Scenario IDs must be unique (case-insensitive)")
        return self


class CaseResult(RenderWitnessModel):
    id: str
    name: str
    status: Literal["passed", "failed", "error"]
    duration_seconds: float = Field(ge=0)
    report: str | None = None
    verdict: str | None = None
    changed_pixels: int | None = None
    change_ratio: float | None = None
    gate: GateResult | None = None
    error: str | None = None


class SuiteResult(RenderWitnessModel):
    schema_version: Literal[1] = 1
    name: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cases: list[CaseResult]

    @property
    def exit_code(self) -> int:
        if any(case.status == "error" for case in self.cases):
            return 2
        return 1 if any(case.status == "failed" for case in self.cases) else 0


def load_suite(path: str | Path) -> SuiteConfig:
    source = Path(path).expanduser()
    try:
        if source.stat().st_size > 2 * 1024 * 1024:
            raise SuiteError("Suite configuration exceeds the 2 MiB limit")
        return SuiteConfig.model_validate_json(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise SuiteError(f"Cannot load suite '{source}': {exc}") from exc


def run_suite(
    config_path: str | Path,
    output_dir: str | Path,
    *,
    provider: VisionProvider | None = None,
) -> SuiteResult:
    """Compare all cases sequentially; operational errors never become passing gates."""
    source = Path(config_path).expanduser().resolve()
    config = load_suite(source)
    output = Path(output_dir).expanduser().resolve()
    inputs = [(source.parent / case.baseline).expanduser().resolve() for case in config.scenarios]
    inputs += [(source.parent / case.candidate).expanduser().resolve() for case in config.scenarios]
    if any(path.is_relative_to(output) for path in [source, *inputs]):
        raise SuiteError("Suite output must not contain its configuration or source images")
    # Reusing nonempty directories could expose stale case reports after a later failed run.
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise SuiteError("Suite output must be a new or empty directory; choose a fresh run path")
    output.mkdir(parents=True, exist_ok=True)
    selected = provider or DemoProvider()
    cases: list[CaseResult] = []
    for scenario in config.scenarios:
        started = perf_counter()
        case_dir = output / "cases" / scenario.id
        error: str | None = None
        report: str | None = None
        result: AnalysisResult | None = None
        gate: GateResult | None = None
        options = DiffOptions.model_validate(
            {
                **config.defaults.model_dump(),
                **scenario.diff.model_dump(exclude_unset=True),
            }
        )
        policy = GatePolicy.model_validate(
            {
                **config.policy.model_dump(),
                **scenario.policy.model_dump(exclude_unset=True),
            }
        )
        baseline = (source.parent / scenario.baseline).expanduser().resolve()
        candidate = (source.parent / scenario.candidate).expanduser().resolve()
        try:
            comparison = compare_images(
                baseline, candidate, ignore_regions=scenario.ignore_regions, **options.model_dump()
            )
            images = case_dir / "images"
            images.mkdir(parents=True, exist_ok=True)
            for path, label in ((baseline, "baseline"), (candidate, "candidate")):
                shutil.copyfile(path, images / f"{label}{path.suffix.lower()}")
            _atomic_write(case_dir / "comparison.json", comparison.model_dump_json(indent=2) + "\n")
            try:
                result = analyze(comparison, baseline, candidate, provider=selected)
            except (ProviderError, AnalysisError, ValidationError) as exc:
                error = str(exc) or type(exc).__name__
                result = AnalysisResult(
                    comparison=comparison,
                    provider="unavailable",
                    verdict=Verdict.REVIEW,
                    summary=(
                        "Semantic analysis unavailable. Inspect the deterministic evidence; "
                        "this case is an operational error."
                    ),
                )
            write_report(
                result, baseline, candidate, case_dir, max_image_bytes=options.max_image_bytes
            )
            report = f"cases/{scenario.id}/index.html"
            if error is None:
                gate = evaluate_policy(result, policy)
        except (ComparisonError, ReportError, OSError, ValidationError) as exc:
            error = str(exc) or type(exc).__name__
        cases.append(
            CaseResult(
                id=scenario.id,
                name=scenario.name or scenario.id,
                status="error"
                if error is not None
                else ("failed" if gate and not gate.passed else "passed"),
                duration_seconds=perf_counter() - started,
                report=report,
                verdict=result.verdict.value if result else None,
                changed_pixels=result.comparison.changed_pixels if result else None,
                change_ratio=result.comparison.change_ratio if result else None,
                gate=gate,
                error=error,
            )
        )
    suite = SuiteResult(name=config.name, cases=cases)
    write_suite_report(suite, output)
    return suite
