"""Opt-in browser verification of the portable report's actual interactions."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from renderwitness.diff import compare_images
from renderwitness.models import AnalysisResult, Finding
from renderwitness.report import ReportPaths, write_report

pytestmark = pytest.mark.skipif(
    os.environ.get("RENDERWITNESS_BROWSER_TESTS") != "1",
    reason="set RENDERWITNESS_BROWSER_TESTS=1 after installing Playwright Chromium",
)


@dataclass
class ReportSession:
    page: Any
    expect: Any
    result: AnalysisResult
    paths: ReportPaths


@pytest.fixture
def browser_report(image_pair: tuple[Path, Path], tmp_path: Path) -> Iterator[ReportSession]:
    playwright_api = pytest.importorskip("playwright.sync_api")
    baseline, candidate = image_pair
    comparison = compare_images(baseline, candidate, min_region_area=1, region_padding=0)
    result = AnalysisResult(
        comparison=comparison,
        provider="browser-test-fixture",
        model="static-fixture-v1",
        summary='<img src="https://example.invalid/injection" onerror="alert(1)">',
        verdict="fail",
        findings=[
            Finding(
                id="critical-cta",
                region_id=comparison.regions[0].id,
                category="text-clipping",
                severity="critical",
                title="Export label is clipped / 导出按钮被裁切",
                description="The primary action no longer shows its complete localized label.",
                confidence=0.98,
                suggestion="Restore intrinsic button sizing.",
            ),
            Finding(
                id="minor-color",
                region_id=comparison.regions[-1].id,
                category="color-change",
                severity="minor",
                title="Secondary color changed",
                description="The secondary element has a different color.",
                confidence=0.85,
            ),
            Finding(
                id="minor-global",
                category="whole-image",
                severity="minor",
                title="Review the whole page",
                description="A whole-image finding has no region assignment.",
                confidence=0.75,
            ),
        ],
    )
    paths = write_report(result, baseline, candidate, tmp_path / "report")
    requests: list[str] = []
    errors: list[str] = []
    dialogs: list[str] = []
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        page.set_default_timeout(5000)

        def record_request(request: Any) -> None:
            if request.url.startswith(("https://", "http://")):
                requests.append(request.url)

        def dismiss_dialog(dialog: Any) -> None:
            dialogs.append(dialog.message)
            dialog.dismiss()

        page.on("request", record_request)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", dismiss_dialog)
        # Any accidental remote request is recorded and blocked before network I/O.
        page.route(re.compile(r"^https?://"), lambda route: route.abort())
        try:
            page.goto(paths.html.as_uri(), wait_until="load")
            yield ReportSession(page=page, expect=playwright_api.expect, result=result, paths=paths)
            assert requests == [], f"Portable report requested external resources: {requests}"
            assert errors == [], f"Report JavaScript errors: {errors}"
            assert dialogs == [], f"Provider content executed a dialog: {dialogs}"
        finally:
            context.close()
            browser.close()


def test_report_tabs_keyboard_slider_and_region_visibility(browser_report: ReportSession) -> None:
    page, expect = browser_report.page, browser_report.expect
    stage = page.locator("#comparison-stage")
    split = page.get_by_role("tab", name="Side by side")
    blend = page.get_by_role("tab", name="Blend", exact=True)
    heatmap = page.get_by_role("tab", name="Diff map")
    expect(stage).to_have_attribute("data-view", "split")
    expect(split).to_have_attribute("aria-selected", "true")
    expect(page.get_by_alt_text("Baseline screenshot", exact=True)).to_be_visible()
    expect(page.get_by_alt_text("Candidate screenshot", exact=True)).to_be_visible()
    expect(page.locator(".heatmap-panel")).to_be_hidden()
    expect(page.locator("#blend-controls")).to_be_hidden()

    split.focus()
    split.press("ArrowRight")
    expect(blend).to_be_focused()
    expect(blend).to_have_attribute("aria-selected", "true")
    expect(split).to_have_attribute("tabindex", "-1")
    expect(stage).to_have_attribute("data-view", "blend")
    expect(stage).to_have_attribute("aria-labelledby", "view-blend")
    expect(page.locator("#blend-controls")).to_be_visible()
    slider = page.get_by_role("slider", name="Candidate opacity")
    slider.fill("73")
    expect(page.locator("#blend-value")).to_have_text("73%")
    expect(page.locator(".candidate-panel img")).to_have_css("opacity", "0.73")
    slider.press("Home")
    expect(page.locator(".candidate-panel img")).to_have_css("opacity", "0")
    slider.press("End")
    expect(page.locator(".candidate-panel img")).to_have_css("opacity", "1")

    heatmap.click()
    expect(stage).to_have_attribute("data-view", "heatmap")
    expect(heatmap).to_have_attribute("aria-selected", "true")
    expect(page.locator(".heatmap-panel")).to_be_visible()
    expect(page.locator(".baseline-panel")).to_be_hidden()
    expect(page.locator(".candidate-panel")).to_be_hidden()
    expect(page.locator("#blend-controls")).to_be_hidden()
    expect(page.locator(".heatmap-panel .roi").first).to_be_visible()
    page.get_by_role("checkbox", name="Show regions").uncheck()
    expect(page.locator(".heatmap-panel .roi").first).to_be_hidden()
    page.get_by_role("checkbox", name="Show regions").check()
    expect(page.locator(".heatmap-panel .roi").first).to_be_visible()

    heatmap.press("ArrowRight")
    expect(split).to_be_focused()
    expect(stage).to_have_attribute("data-view", "split")
    blend.click()
    split.click()
    expect(stage).to_have_attribute("data-view", "split")


def test_report_finding_focus_reset_and_severity_filters(browser_report: ReportSession) -> None:
    page, expect = browser_report.page, browser_report.expect
    critical = page.locator('.finding[data-severity="critical"]')
    button = critical.locator(".finding-select")
    region_id = browser_report.result.findings[0].region_id
    matching_regions = page.locator(f'.roi[data-region="{region_id}"]')
    page.get_by_role("checkbox", name="Show regions").uncheck()
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")
    expect(critical).to_have_class(re.compile(r"\bis-selected\b"))
    expect(page.get_by_role("checkbox", name="Show regions")).to_be_checked()
    expect(page.locator("#selection-status")).to_have_text(f"Focused evidence: {region_id}")
    assert matching_regions.count() == 3
    for region in matching_regions.all():
        expect(region).to_have_class(re.compile(r"\bis-selected\b"))
    expect(page.locator(".baseline-panel .roi.is-selected")).to_be_visible()
    page.get_by_role("button", name="Clear selection").click()
    expect(button).to_have_attribute("aria-pressed", "false")
    expect(page.locator(".roi.is-selected")).to_have_count(0)
    expect(page.locator("#clear-selection")).to_be_hidden()

    # Clicking the same finding twice also clears the selection.
    button.click()
    button.click()
    expect(button).to_have_attribute("aria-pressed", "false")
    whole_image = page.get_by_role("button", name="Review the whole page")
    whole_image.click()
    expect(page.locator("#selection-status")).to_have_text(
        "Whole-image finding — review the full comparison."
    )
    expect(page.locator(".roi.is-selected")).to_have_count(0)

    severity = page.get_by_label("SEVERITY", exact=True)
    severity.select_option("critical")
    expect(page.locator(".finding:visible")).to_have_count(1)
    expect(critical).to_be_visible()
    expect(page.locator("#visible-count")).to_have_text("1")
    expect(page.locator("#clear-selection")).to_be_hidden()
    severity.select_option("minor")
    expect(page.locator(".finding:visible")).to_have_count(2)
    expect(critical).to_be_hidden()
    expect(page.locator("#visible-count")).to_have_text("2")
    severity.select_option("major")
    expect(page.locator(".finding:visible")).to_have_count(0)
    expect(page.locator("#filter-empty")).to_be_visible()
    expect(page.locator("#visible-count")).to_have_text("0")
    severity.select_option("all")
    expect(page.locator(".finding:visible")).to_have_count(3)
    expect(page.locator("#filter-empty")).to_be_hidden()


def test_report_download_preserves_canonical_json_and_escaped_text(
    browser_report: ReportSession, tmp_path: Path
) -> None:
    page, expect = browser_report.page, browser_report.expect
    expect(page.locator(".assessment p")).to_have_text(browser_report.result.summary)
    expect(page.locator(".assessment img")).to_have_count(0)
    page.locator(".evidence summary").click()
    expect(page.locator("#structured-result")).to_be_visible()
    with page.expect_download() as download_info:
        page.get_by_role("button", name="Download JSON").click()
    download = download_info.value
    assert download.suggested_filename == "renderwitness-report.json"
    output = tmp_path / "download.json"
    download.save_as(output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == json.loads(browser_report.paths.json.read_text(encoding="utf-8"))
    assert payload == browser_report.result.model_dump(mode="json")
