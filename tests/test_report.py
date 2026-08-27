from __future__ import annotations

import json
from pathlib import Path

import pytest

from renderwitness.analyzer import analyze
from renderwitness.diff import compare_images
from renderwitness.models import Finding, ProviderResult
from renderwitness.report import ReportError, render_html, write_report


class FixedProvider:
    name = "fixed"

    def __init__(self, result: ProviderResult) -> None:
        self.result = result

    def analyze(self, *args: object) -> ProviderResult:
        return self.result


def build_analysis(
    baseline: Path,
    candidate: Path,
    *,
    malicious: bool = False,
):
    comparison = compare_images(baseline, candidate, min_region_area=1)
    finding = Finding(
        id="finding-001",
        region_id=comparison.regions[0].id,
        category="text-clipping",
        severity="critical",
        title="<script>alert('title')</script>" if malicious else "CTA is clipped",
        description=(
            "<img src=x onerror=alert('description')>"
            if malicious
            else "The Chinese label is no longer fully visible."
        ),
        confidence=0.97,
        suggestion="Use width: auto & add a localized viewport test.",
    )
    provider_result = ProviderResult(
        provider="fixed",
        model="fixture-v1",
        summary=(
            "</p><script>alert('summary')</script>" if malicious else "One critical regression."
        ),
        verdict="fail",
        findings=[finding],
    )
    return analyze(
        comparison,
        baseline,
        candidate,
        provider=FixedProvider(provider_result),
    )


def test_write_report_creates_portable_html_and_canonical_json(
    image_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    baseline, candidate = image_pair
    result = build_analysis(baseline, candidate)
    output = tmp_path / "report"

    paths = write_report(result, baseline, candidate, output)

    assert paths.html == (output / "index.html").resolve()
    assert paths.json == (output / "report.json").resolve()
    html = paths.html.read_text(encoding="utf-8")
    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    assert html.startswith("<!doctype html>")
    assert html.count("data:image/png;base64,") == 2
    assert html.count('class="roi"') == len(result.comparison.regions)
    assert "fixed · fixture-v1" in html
    assert "CTA is clipped" in html
    assert payload == result.model_dump(mode="json")
    assert payload["comparison"]["baseline"]["sha256"]
    assert payload["findings"][0]["region_id"] in {
        region["id"] for region in payload["comparison"]["regions"]
    }


def test_report_escapes_untrusted_provider_text(
    image_pair: tuple[Path, Path],
) -> None:
    baseline, candidate = image_pair
    result = build_analysis(baseline, candidate, malicious=True)

    document = render_html(result, baseline, candidate)

    assert "<script>alert('title')</script>" not in document
    assert "<img src=x onerror=alert('description')>" not in document
    assert "</p><script>alert('summary')</script>" not in document
    assert "&lt;script&gt;alert" in document
    assert "&lt;img src=x onerror=alert" in document


@pytest.mark.parametrize(
    ("html_name", "json_name"),
    [
        ("../escape.html", "report.json"),
        ("index.txt", "report.json"),
        ("index.html", "nested/report.json"),
        ("index.html", "report.txt"),
    ],
)
def test_report_filenames_cannot_escape_output_directory(
    image_pair: tuple[Path, Path],
    tmp_path: Path,
    html_name: str,
    json_name: str,
) -> None:
    baseline, candidate = image_pair
    result = build_analysis(baseline, candidate)

    with pytest.raises(ReportError, match="filename|filenames"):
        write_report(
            result,
            baseline,
            candidate,
            tmp_path / "report",
            html_name=html_name,
            json_name=json_name,
        )


def test_report_rejects_invalid_or_oversized_embed_inputs(
    image_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    baseline, candidate = image_pair
    result = build_analysis(baseline, candidate)
    invalid = tmp_path / "fake.png"
    invalid.write_text("not a PNG", encoding="utf-8")

    with pytest.raises(ReportError, match="invalid image"):
        render_html(result, invalid, candidate)
    with pytest.raises(ReportError, match="limit"):
        render_html(result, baseline, candidate, max_image_bytes=1)


def test_report_output_must_be_a_directory(image_pair: tuple[Path, Path], tmp_path: Path) -> None:
    baseline, candidate = image_pair
    result = build_analysis(baseline, candidate)
    occupied = tmp_path / "occupied"
    occupied.write_text("file, not directory", encoding="utf-8")

    with pytest.raises(ReportError, match="directory|create output"):
        write_report(result, baseline, candidate, occupied)
