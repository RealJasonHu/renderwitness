from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image
from pydantic import ValidationError

from renderwitness.capture import CaptureError, CaptureOptions, capture_page


@pytest.fixture
def fake_browser(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    manager = MagicMock()
    playwright = manager.__enter__.return_value
    browser = playwright.chromium.launch.return_value
    browser.version = "123.0.test"
    context = browser.new_context.return_value
    page = context.new_page.return_value
    page.url = "https://other-user:other-pass@example.test/redirect?token=hidden#private"
    page.goto.return_value.status = 200
    buffer = io.BytesIO()
    Image.new("RGB", (390, 844), "white").save(buffer, format="PNG")
    page.screenshot.return_value = buffer.getvalue()
    manager.browser = browser
    manager.context = context
    manager.page = page
    monkeypatch.setattr("renderwitness.capture._load_playwright", lambda: lambda: manager)
    return manager


def test_capture_controls_browser_and_records_redacted_provenance(
    fake_browser: MagicMock, tmp_path: Path
) -> None:
    options = CaptureOptions(
        width=390,
        height=844,
        locale="zh-CN",
        color_scheme="dark",
        timeout_ms=4200,
        wait_for="main",
        mask_selectors=("#live-clock", ".private"),
    )
    source = "https://username:password@example.test/dashboard?api_key=secret#session"
    result = capture_page(source, tmp_path / "nested" / "page.png", options=options)

    browser, context, page = fake_browser.browser, fake_browser.context, fake_browser.page
    browser.new_context.assert_called_once_with(
        viewport={"width": 390, "height": 844},
        screen={"width": 390, "height": 844},
        device_scale_factor=1,
        locale="zh-CN",
        timezone_id="UTC",
        color_scheme="dark",
        reduced_motion="reduce",
        service_workers="block",
        accept_downloads=False,
    )
    page.goto.assert_called_once_with(source, wait_until="load", timeout=4200)
    context.set_default_timeout.assert_called_once_with(4200)
    context.set_default_navigation_timeout.assert_called_once_with(4200)
    page.locator.assert_any_call("main")
    page.locator.assert_any_call("#live-clock")
    page.locator.assert_any_call(".private")
    assert page.locator.return_value.first.wait_for.call_count == 2
    assert "document.fonts.ready" in page.evaluate.call_args.args[0]
    assert page.evaluate.call_args.args[1] == 4200
    screenshot_options = page.screenshot.call_args.kwargs
    assert screenshot_options["animations"] == "disabled"
    assert screenshot_options["caret"] == "hide"
    assert screenshot_options["scale"] == "css"
    assert screenshot_options["full_page"] is False
    assert len(screenshot_options["mask"]) == 2
    context.close.assert_called_once()
    browser.close.assert_called_once()
    fake_browser.__exit__.assert_called_once()

    assert result.screenshot_path.read_bytes() == page.screenshot.return_value
    assert result.manifest_path == result.screenshot_path.with_suffix(".capture.json")
    raw_manifest = result.manifest_path.read_text()
    manifest = json.loads(raw_manifest)
    assert manifest["source_url"] == "https://example.test/dashboard"
    assert manifest["final_url"] == "https://example.test/redirect"
    assert manifest["width"] == 390 and manifest["height"] == 844
    assert manifest["sha256"] == hashlib.sha256(result.screenshot_path.read_bytes()).hexdigest()
    assert manifest["browser_version"] == "123.0.test"
    assert manifest["options"]["mask_selectors"] == ["#live-clock", ".private"]
    for secret in ("username", "password", "secret", "other-user", "hidden", "api_key"):
        assert secret not in raw_manifest


@pytest.mark.parametrize("stage", ["goto", "evaluate", "screenshot", "mask"])
def test_capture_failure_closes_resources_and_keeps_existing_outputs(
    fake_browser: MagicMock, tmp_path: Path, stage: str
) -> None:
    error = RuntimeError("https://user:password@test.invalid/?api_key=secret")
    if stage == "mask":
        fake_browser.page.locator.return_value.first.wait_for.side_effect = error
    else:
        getattr(fake_browser.page, stage).side_effect = error
    output = tmp_path / "existing.png"
    manifest = output.with_suffix(".capture.json")
    output.write_bytes(b"old screenshot")
    manifest.write_text("old manifest")

    with pytest.raises(CaptureError) as caught:
        capture_page(
            "https://example.test/?token=secret",
            output,
            options=CaptureOptions(mask_selectors=(".dynamic",)),
        )

    assert "secret" not in str(caught.value)
    assert "password" not in str(caught.value)
    assert caught.value.__suppress_context__
    fake_browser.context.close.assert_called_once()
    fake_browser.browser.close.assert_called_once()
    assert output.read_bytes() == b"old screenshot"
    assert manifest.read_text() == "old manifest"


def test_context_creation_failure_still_closes_browser(
    fake_browser: MagicMock, tmp_path: Path
) -> None:
    fake_browser.browser.new_context.side_effect = RuntimeError("invalid locale")
    with pytest.raises(CaptureError, match="creating the browser context"):
        capture_page("https://example.test", tmp_path / "page.png")
    fake_browser.browser.close.assert_called_once()
    assert not (tmp_path / "page.png").exists()


def test_launch_error_explains_browser_installation(
    fake_browser: MagicMock, tmp_path: Path
) -> None:
    fake_browser.__enter__.return_value.chromium.launch.side_effect = RuntimeError("missing")
    with pytest.raises(CaptureError, match="python -m playwright install chromium"):
        capture_page("https://example.test", tmp_path / "page.png")
    fake_browser.__exit__.assert_called_once()


def test_missing_optional_dependency_is_actionable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def missing_module(name: str) -> None:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("renderwitness.capture.importlib.import_module", missing_module)
    with pytest.raises(CaptureError, match=r"renderwitness\[capture\]"):
        capture_page("https://example.test", tmp_path / "page.png")
    assert not (tmp_path / "page.png").exists()


@pytest.mark.parametrize("status", [401, 404, 500])
def test_http_failure_is_not_accepted_as_baseline(
    fake_browser: MagicMock, tmp_path: Path, status: int
) -> None:
    fake_browser.page.goto.return_value.status = status
    with pytest.raises(CaptureError, match=f"HTTP {status}"):
        capture_page("https://example.test", tmp_path / "page.png")
    fake_browser.page.screenshot.assert_not_called()
    fake_browser.context.close.assert_called_once()
    fake_browser.browser.close.assert_called_once()


def test_local_file_capture_supports_full_page(fake_browser: MagicMock, tmp_path: Path) -> None:
    source = (tmp_path / "a page.html").as_uri()
    fake_browser.page.goto.return_value = None
    fake_browser.page.url = source
    result = capture_page(source, tmp_path / "page.PNG", options=CaptureOptions(full_page=True))
    assert result.metadata.source_url == source
    assert fake_browser.page.screenshot.call_args.kwargs["full_page"] is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "javascript:alert(1)",
        "data:text/html,hello",
        "ftp://example.test",
        "https:///bad",
        "file://remote-host/path",
        "https://example.test:wrong/",
        "https://example.test/\nsecret",
    ],
)
def test_unsupported_urls_fail_before_loading_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str
) -> None:
    load = MagicMock(side_effect=AssertionError("browser must not load"))
    monkeypatch.setattr("renderwitness.capture._load_playwright", load)
    with pytest.raises(CaptureError, match="URL"):
        capture_page(url, tmp_path / "page.png")
    load.assert_not_called()


def test_non_png_output_fails_before_loading_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    load = MagicMock(side_effect=AssertionError("browser must not load"))
    monkeypatch.setattr("renderwitness.capture._load_playwright", load)
    with pytest.raises(CaptureError, match=".png extension"):
        capture_page("https://example.test", tmp_path / "page.jpeg")
    load.assert_not_called()


def test_capture_replaces_output_symlink_without_modifying_its_target(
    fake_browser: MagicMock, tmp_path: Path
) -> None:
    target = tmp_path / "keep.png"
    target.write_bytes(b"existing source")
    output = tmp_path / "capture.png"
    output.symlink_to(target)
    result = capture_page("https://example.test", output)
    assert result.screenshot_path == output
    assert not output.is_symlink()
    assert output.read_bytes() == fake_browser.page.screenshot.return_value
    assert target.read_bytes() == b"existing source"


@pytest.mark.parametrize("directory_name", ["page.png", "page.capture.json"])
def test_output_directory_collision_keeps_existing_files_without_launching_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, directory_name: str
) -> None:
    load = MagicMock(side_effect=AssertionError("browser must not load"))
    monkeypatch.setattr("renderwitness.capture._load_playwright", load)
    (tmp_path / directory_name).mkdir()
    if directory_name != "page.png":
        (tmp_path / "page.png").write_bytes(b"keep original")
    with pytest.raises(CaptureError, match="must not be directories"):
        capture_page("https://example.test", tmp_path / "page.png")
    load.assert_not_called()
    if directory_name != "page.png":
        assert (tmp_path / "page.png").read_bytes() == b"keep original"


def test_context_cleanup_failure_does_not_skip_browser_cleanup(
    fake_browser: MagicMock, tmp_path: Path
) -> None:
    fake_browser.page.goto.side_effect = RuntimeError("navigation failed")
    fake_browser.context.close.side_effect = RuntimeError("context cleanup failed")
    with pytest.raises(CaptureError, match="loading the page"):
        capture_page("https://example.test", tmp_path / "page.png")
    fake_browser.browser.close.assert_called_once()
    fake_browser.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width": 0},
        {"height": 8193},
        {"width": True},
        {"timeout_ms": 0},
        {"timeout_ms": 300001},
        {"locale": " "},
        {"color_scheme": "sepia"},
        {"wait_for": " "},
        {"mask_selectors": [" "]},
        {"unexpected": "setting"},
    ],
)
def test_invalid_capture_options_fail_early(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CaptureOptions.model_validate(kwargs)


@pytest.mark.skipif(
    os.environ.get("RENDERWITNESS_BROWSER_TESTS") != "1",
    reason="set RENDERWITNESS_BROWSER_TESTS=1 after installing Playwright Chromium",
)
def test_real_browser_masks_clock_and_detects_fixture_regressions(tmp_path: Path) -> None:
    pytest.importorskip("playwright.sync_api")
    from renderwitness.cli import main
    from renderwitness.diff import compare_images

    fixtures = Path(__file__).resolve().parents[1] / "examples" / "web"
    options = CaptureOptions(width=390, height=844, mask_selectors=("#live-clock",))
    baseline = capture_page(
        (fixtures / "baseline.html").as_uri(), tmp_path / "a.png", options=options
    )
    repeat = capture_page(
        (fixtures / "baseline.html").as_uri(), tmp_path / "b.png", options=options
    )
    candidate_path = tmp_path / "c.png"
    assert (
        main(
            [
                "capture",
                (fixtures / "candidate.html").as_uri(),
                "-o",
                str(candidate_path),
                "--width",
                "390",
                "--height",
                "844",
                "--mask",
                "#live-clock",
                "--wait-for",
                "main",
            ]
        )
        == 0
    )
    assert baseline.metadata.sha256 == repeat.metadata.sha256
    diff = compare_images(baseline.screenshot_path, candidate_path)
    assert (diff.width, diff.height) == (390, 844)
    assert diff.changed_pixels > 1000
    assert diff.regions
    report_dir = tmp_path / "report"
    assert (
        main(
            [
                "compare",
                str(baseline.screenshot_path),
                str(candidate_path),
                "-o",
                str(report_dir),
                "--fail-on-change",
            ]
        )
        == 1
    )
    assert (report_dir / "index.html").is_file()
    assert (
        json.loads((report_dir / "report.json").read_text())["comparison"]["changed_pixels"] > 1000
    )
