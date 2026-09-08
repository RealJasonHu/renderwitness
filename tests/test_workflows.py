from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from renderwitness.analyzer import compare_and_analyze
from renderwitness.cli import main
from renderwitness.diff import ComparisonError, compare_images
from renderwitness.models import BoundingBox, ComparisonResult, Finding, Severity, Verdict
from renderwitness.policy import GatePolicy, evaluate_policy
from renderwitness.providers import ProviderError
from renderwitness.suite import SuiteConfig, SuiteError, load_suite, run_suite


def config_file(tmp_path: Path, scenarios: list[dict], **kwargs: object) -> Path:
    path = tmp_path / "suite.json"
    path.write_text(json.dumps({"version": 1, "scenarios": scenarios, **kwargs}), encoding="utf-8")
    return path


def test_ignored_pixels_use_union_and_unmasked_denominator(tmp_path: Path) -> None:
    baseline, candidate = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (10, 10), "white").save(baseline)
    changed = Image.new("RGB", (10, 10), "white")
    ImageDraw.Draw(changed).rectangle((0, 0, 5, 1), fill="black")
    changed.save(candidate)
    result = compare_images(
        baseline,
        candidate,
        min_region_area=1,
        region_padding=0,
        ignore_regions=[
            BoundingBox(x=0, y=0, width=2, height=2),
            BoundingBox(x=1, y=0, width=2, height=2),
        ],
    )
    assert result.ignored_pixels == 6
    assert result.changed_pixels == 6
    assert result.change_ratio == pytest.approx(6 / 94)
    assert result.regions[0].bbox.x == 3
    assert result.baseline.sha256 == compare_images(baseline, baseline).baseline.sha256


@pytest.mark.parametrize(
    "box", [BoundingBox(x=0, y=0, width=96, height=72), BoundingBox(x=95, y=71, width=2, height=2)]
)
def test_invalid_masks_cannot_hide_a_whole_screenshot(image_pair, box) -> None:
    with pytest.raises(ComparisonError, match="leave at least|exceeds"):
        compare_images(*image_pair, ignore_regions=[box])


def test_change_budget_boundary_and_provider_verdict_are_separate(image_pair) -> None:
    result = compare_and_analyze(*image_pair)
    boundary = result.comparison.change_ratio
    assert evaluate_policy(result, GatePolicy()).passed
    assert evaluate_policy(result, GatePolicy(max_change_ratio=boundary)).passed
    assert not evaluate_policy(result, GatePolicy(max_change_ratio=boundary - 0.000001)).passed
    result.verdict = Verdict.FAIL
    assert evaluate_policy(result, GatePolicy()).passed
    assert not evaluate_policy(result, GatePolicy(fail_on_review=True)).passed


def test_severity_gate_respects_confidence_and_inclusive_boundary(image_pair) -> None:
    result = compare_and_analyze(*image_pair)
    result.findings = [
        Finding(
            id="low-confidence",
            category="text",
            severity=Severity.CRITICAL,
            title="Possible issue",
            description="Visible difference",
            confidence=0.79,
        )
    ]
    policy = GatePolicy(fail_on_severity=Severity.MAJOR, min_confidence=0.8)
    assert evaluate_policy(result, policy).passed
    result.findings[0].confidence = 0.8
    assert not evaluate_policy(result, policy).passed
    result.findings[0].severity = Severity.MINOR
    assert evaluate_policy(result, policy).passed


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_policy_rejects_nonfinite_or_out_of_range_values(value: float) -> None:
    with pytest.raises(ValidationError):
        GatePolicy(max_change_ratio=value)


def test_suite_aggregates_pass_failure_error_and_continues(image_pair, tmp_path: Path) -> None:
    baseline, candidate = image_pair
    config = config_file(
        tmp_path,
        [
            {"id": "regression", "baseline": baseline.name, "candidate": candidate.name},
            {"id": "missing", "baseline": "missing.png", "candidate": candidate.name},
            {"id": "unchanged", "baseline": baseline.name, "candidate": baseline.name},
        ],
        policy={"max_change_ratio": 0},
    )
    result = run_suite(config, tmp_path / "output")
    assert result.exit_code == 2
    assert [case.status for case in result.cases] == ["failed", "error", "passed"]
    payload = json.loads((tmp_path / "output/summary.json").read_text())
    assert payload["counts"] == {"passed": 1, "failed": 1, "error": 1}
    root = ET.parse(tmp_path / "output/junit.xml").getroot()
    assert root.attrib["tests"] == "3"
    assert len(root.findall("testcase/failure")) == len(root.findall("testcase/error")) == 1
    assert (
        tmp_path / "output/cases/unchanged/images/baseline.png"
    ).read_bytes() == baseline.read_bytes()
    assert (tmp_path / "output/cases/regression/comparison.json").is_file()
    assert "cases/unchanged/index.html" in (tmp_path / "output/summary.md").read_text()


def test_explicit_case_overrides_inherit_and_can_clear_policy(image_pair, tmp_path: Path) -> None:
    baseline, candidate = image_pair
    config = config_file(
        tmp_path,
        [
            {"id": "inherited", "baseline": baseline.name, "candidate": candidate.name},
            {
                "id": "overridden",
                "baseline": baseline.name,
                "candidate": candidate.name,
                "diff": {"threshold": 255},
                "policy": {"max_change_ratio": None},
            },
        ],
        defaults={"min_region_area": 1, "threshold": 0},
        policy={"max_change_ratio": 0},
    )
    result = run_suite(config, tmp_path / "output")
    assert result.exit_code == 1
    assert result.cases[0].status == "failed"
    assert result.cases[1].status == "passed"
    report = json.loads((tmp_path / "output/cases/overridden/report.json").read_text())
    assert report["comparison"]["threshold"] == 255
    assert report["comparison"]["min_region_area"] == 1
    assert result.cases[1].gate.policy.max_change_ratio is None


class BrokenProvider:
    name = "broken"

    def __init__(self, message: str = "Backend unavailable") -> None:
        self.message = message

    def analyze(self, *args: object):
        raise ProviderError(self.message)


@pytest.mark.parametrize("message", ["Backend unavailable", ""])
def test_failed_provider_retains_evidence_but_never_passes(
    image_pair, tmp_path: Path, message
) -> None:
    baseline, candidate = image_pair
    config = config_file(
        tmp_path, [{"id": "backend", "baseline": baseline.name, "candidate": candidate.name}]
    )
    result = run_suite(config, tmp_path / "output", provider=BrokenProvider(message))
    case = result.cases[0]
    assert result.exit_code == 2
    assert case.status == "error" and case.gate is None
    assert case.report == "cases/backend/index.html"
    payload = json.loads((tmp_path / "output/cases/backend/report.json").read_text())
    assert payload["provider"] == "unavailable"
    assert payload["comparison"]["changed_pixels"] > 0
    assert not payload["findings"]


def test_loaded_comparison_rejects_fabricated_exclusion_count(image_pair) -> None:
    payload = compare_images(*image_pair).model_dump()
    payload["ignored_pixels"] = 1
    payload["change_ratio"] = payload["changed_pixels"] / (payload["total_pixels"] - 1)
    with pytest.raises(ValidationError, match="union area"):
        ComparisonResult.model_validate(payload)


def test_failed_early_rerun_replaces_old_passing_artifacts(image_pair, tmp_path) -> None:
    baseline, candidate = image_pair
    output = tmp_path / "output"
    assert main(["compare", str(baseline), str(candidate), "-o", str(output)]) == 0
    candidate.write_text("corrupted")
    assert main(["compare", str(baseline), str(candidate), "-o", str(output)]) == 2
    assert json.loads((output / "gate.json").read_text())["passed"] is False
    assert json.loads((output / "report.json").read_text())["status"] == "error"
    assert "Comparison did not complete" in (output / "index.html").read_text()


def test_compare_failed_provider_overwrites_stale_gate(image_pair, tmp_path, monkeypatch) -> None:
    output = tmp_path / "output"
    assert main(["compare", *map(str, image_pair), "-o", str(output)]) == 0
    monkeypatch.setattr("renderwitness.cli.create_provider", lambda *a, **kw: BrokenProvider())
    assert main(["compare", *map(str, image_pair), "-o", str(output)]) == 2
    assert json.loads((output / "gate.json").read_text())["passed"] is False
    assert json.loads((output / "report.json").read_text())["provider"] == "unavailable"


@pytest.mark.parametrize("ids", [["../escape"], ["a", "A"], ["a/b"], [".."], ["x.y"]])
def test_suite_ids_cannot_escape_or_collide(ids: list[str]) -> None:
    with pytest.raises(ValidationError):
        SuiteConfig.model_validate(
            {
                "scenarios": [
                    {"id": identifier, "baseline": "a.png", "candidate": "b.png"}
                    for identifier in ids
                ]
            }
        )


def test_suite_configuration_and_output_errors_do_not_clobber_sources(image_pair, tmp_path) -> None:
    config = config_file(
        tmp_path, [{"id": "a", "baseline": "baseline.png", "candidate": "candidate.png"}]
    )
    with pytest.raises(SuiteError, match="must not contain"):
        run_suite(config, tmp_path)
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "precious.txt").write_text("keep")
    with pytest.raises(SuiteError, match="new or empty"):
        run_suite(config, occupied)
    assert (occupied / "precious.txt").read_text() == "keep"
    config.write_text('{"version": 7, "scenarios": []}')
    with pytest.raises(SuiteError):
        load_suite(config)


def test_summaries_escape_untrusted_labels_in_html_markdown_and_xml(image_pair, tmp_path) -> None:
    config = config_file(
        tmp_path,
        [
            {
                "id": "safe",
                "name": "<script>x</script>|\n界面\x01",
                "baseline": "baseline.png",
                "candidate": "candidate.png",
            }
        ],
        name="<img src=x onerror=alert(1)>",
    )
    assert run_suite(config, tmp_path / "output").exit_code == 0
    html = (tmp_path / "output/index.html").read_text()
    assert "<script>x</script>" not in html
    assert "<img src=x" not in html
    assert "&#124;" in (tmp_path / "output/summary.md").read_text()
    ET.parse(tmp_path / "output/junit.xml")


def test_cli_suite_and_masked_comparison(image_pair, tmp_path) -> None:
    config = config_file(
        tmp_path,
        [{"id": "a", "baseline": "baseline.png", "candidate": "candidate.png"}],
        policy={"max_change_ratio": 0},
    )
    assert main(["suite", str(config), "-o", str(tmp_path / "suite-output")]) == 1
    assert (
        main(
            [
                "compare",
                *map(str, image_pair),
                "--ignore-region",
                "12,10,20,16",
                "--ignore-region",
                "68,48,14,14",
                "--max-change-ratio",
                "0",
                "-o",
                str(tmp_path / "masked"),
            ]
        )
        == 0
    )


@pytest.mark.parametrize(
    "option,value",
    [("--max-change-ratio", "nan"), ("--min-confidence", "inf"), ("--ignore-region", "1,2,0,4")],
)
def test_cli_rejects_invalid_gate_or_mask_arguments(option, value) -> None:
    with pytest.raises(SystemExit) as error:
        main(["compare", "a.png", "b.png", option, value])
    assert error.value.code == 2
