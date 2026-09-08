"""Optional, reproducible Chromium capture with redacted provenance.

Importing this module does not import Playwright or launch a browser. Install
``renderwitness[capture]`` and run ``python -m playwright install chromium``
before calling :func:`capture_page`.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from PIL import Image
from pydantic import ConfigDict, Field, field_validator

from renderwitness.models import RenderWitnessModel


class CaptureError(RuntimeError):
    """Capture could not complete; messages deliberately omit browser error text."""


class CaptureOptions(RenderWitnessModel):
    """Browser settings shared by a baseline and its candidate.

    ``full_page=False`` produces exactly the requested viewport dimensions.
    Dynamic content such as clocks needs an explicit mask or application fixture.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    width: int = Field(default=1280, ge=1, le=8192, strict=True)
    height: int = Field(default=800, ge=1, le=8192, strict=True)
    locale: str = Field(default="en-US", min_length=1, max_length=100)
    color_scheme: Literal["light", "dark", "no-preference"] = "light"
    reduced_motion: Literal["reduce", "no-preference"] = "reduce"
    timeout_ms: int = Field(default=30_000, ge=1, le=300_000, strict=True)
    full_page: bool = False
    wait_for: str | None = Field(default=None, min_length=1, max_length=4096)
    mask_selectors: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("mask_selectors")
    @classmethod
    def validate_selectors(cls, selectors: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(selector.strip() for selector in selectors)
        if any(not selector or len(selector) > 4096 for selector in cleaned):
            raise ValueError("mask selectors must contain 1 to 4096 characters")
        return cleaned


class CaptureMetadata(RenderWitnessModel):
    """Serializable capture provenance; URLs exclude credentials, query and fragment."""

    schema_version: Literal["capture-v1"] = "capture-v1"
    source_url: str
    final_url: str
    captured_at: datetime
    browser: Literal["chromium"] = "chromium"
    browser_version: str
    options: CaptureOptions
    device_scale_factor: Literal[1] = 1
    timezone_id: Literal["UTC"] = "UTC"
    animations: Literal["disabled"] = "disabled"
    caret: Literal["hide"] = "hide"
    mask_color: Literal["#7C3AED"] = "#7C3AED"
    screenshot: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    byte_size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CaptureResult(RenderWitnessModel):
    """Paths to a PNG and JSON manifest, plus the validated manifest contents."""

    screenshot_path: Path
    manifest_path: Path
    metadata: CaptureMetadata


def _load_playwright() -> Any:
    try:
        return importlib.import_module("playwright.sync_api").sync_playwright
    except ImportError:
        raise CaptureError(
            "Browser capture requires the optional dependency. Install it with "
            "pip install 'renderwitness[capture]', then run "
            "python -m playwright install chromium."
        ) from None


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url or any(ord(char) < 32 for char in url):
        raise CaptureError("Capture URL must be a non-empty http, https, or local file URL.")
    try:
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            # Validate the port before passing the URL to the browser.
            _ = parsed.port
            return url
        if parsed.scheme == "file" and parsed.netloc in {"", "localhost"} and parsed.path:
            return url
    except ValueError:
        pass
    raise CaptureError("Capture URL must use http, https, or a local file:// URL.")


def _redact_url(url: str) -> str:
    """Retain URL paths, but omit userinfo and all query/fragment values."""
    try:
        parsed = urlsplit(url)
        authority = parsed.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))
    except ValueError:
        return "[unavailable]"


def _atomic_write(path: Path, contents: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".capture-", delete=False) as f:
            temporary = Path(f.name)
            f.write(contents)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


# The sole page evaluation waits for font readiness, with a bounded timeout.
# A font request that never resolves must not leave a capture running forever.
_FONTS_READY = """async (timeout) => {
    let timer;
    try {
        await Promise.race([
            document.fonts.ready,
            new Promise((_, reject) => {
                timer = setTimeout(() => reject(new Error('Font loading timed out')), timeout);
            })
        ]);
    } finally { clearTimeout(timer); }
}"""


def capture_page(
    url: str,
    output_path: str | Path,
    *,
    options: CaptureOptions | None = None,
) -> CaptureResult:
    """Capture a page to PNG and ``<stem>.capture.json`` using a fresh Chromium context.

    Existing output files are replaced only after a screenshot succeeds. Each
    output file is replaced atomically. This is a synchronous API; async callers
    should use a worker thread. Timeouts apply to each browser operation, not the
    total duration. HTTP error pages (status >= 400) are rejected.

    URL credentials, query strings and fragments never enter the manifest or
    RenderWitness error messages. URL paths, CSS selectors and page pixels are
    retained, so callers must avoid sensitive paths and mask sensitive content.
    """
    url = _validate_url(url)
    selected = options if options is not None else CaptureOptions()
    try:
        requested = Path(output_path).expanduser()
        # Resolve the parent only: following the leaf could overwrite a symlink's
        # target instead of replacing the explicitly requested screenshot path.
        output = requested.parent.resolve() / requested.name
    except (OSError, RuntimeError, ValueError):
        raise CaptureError("Cannot resolve the capture output path.") from None
    if output.suffix.lower() != ".png":
        raise CaptureError("Capture output must have a .png extension.")
    manifest = output.with_suffix(".capture.json")
    try:
        if output.is_dir() or manifest.is_dir():
            raise CaptureError("Screenshot and manifest output paths must not be directories.")
    except (OSError, ValueError):
        raise CaptureError("Cannot access the capture output paths.") from None
    sync_playwright = _load_playwright()
    stage = "starting Chromium"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, timeout=selected.timeout_ms)
            try:
                stage = "creating the browser context"
                context = browser.new_context(
                    viewport={"width": selected.width, "height": selected.height},
                    screen={"width": selected.width, "height": selected.height},
                    device_scale_factor=1,
                    locale=selected.locale,
                    timezone_id="UTC",
                    color_scheme=selected.color_scheme,
                    reduced_motion=selected.reduced_motion,
                    service_workers="block",
                    accept_downloads=False,
                )
                try:
                    context.set_default_timeout(selected.timeout_ms)
                    context.set_default_navigation_timeout(selected.timeout_ms)
                    page = context.new_page()
                    stage = "loading the page"
                    response = page.goto(url, wait_until="load", timeout=selected.timeout_ms)
                    if response is not None and response.status >= 400:
                        raise CaptureError(f"Capture navigation returned HTTP {response.status}.")
                    if selected.wait_for:
                        stage = "waiting for the requested selector"
                        page.locator(selected.wait_for).wait_for(
                            state="visible", timeout=selected.timeout_ms
                        )
                    stage = "waiting for fonts"
                    page.evaluate(_FONTS_READY, selected.timeout_ms)
                    masks = []
                    for selector in selected.mask_selectors:
                        stage = "waiting for a mask selector"
                        locator = page.locator(selector)
                        # Catch misspellings: silently absent masks can expose content.
                        locator.first.wait_for(state="attached", timeout=selected.timeout_ms)
                        masks.append(locator)
                    stage = "taking the screenshot"
                    screenshot = page.screenshot(
                        type="png",
                        full_page=selected.full_page,
                        animations="disabled",
                        caret="hide",
                        scale="css",
                        mask=masks,
                        mask_color="#7C3AED",
                        timeout=selected.timeout_ms,
                    )
                    final_url = _redact_url(page.url)
                    browser_version = browser.version
                finally:
                    with suppress(Exception):
                        context.close()
            finally:
                with suppress(Exception):
                    browser.close()
    except CaptureError:
        raise
    except Exception:
        hint = (
            " Run python -m playwright install chromium to install the browser. "
            "For an async application, call capture_page in a worker thread."
            if stage == "starting Chromium"
            else " Check the page, selectors, and timeout settings."
        )
        raise CaptureError(f"Capture failed while {stage}.{hint}") from None

    try:
        with Image.open(io.BytesIO(screenshot)) as image:
            width, height = image.size
        metadata = CaptureMetadata(
            source_url=_redact_url(url),
            final_url=final_url,
            captured_at=datetime.now(UTC),
            browser_version=browser_version,
            options=selected,
            screenshot=output.name,
            width=width,
            height=height,
            byte_size=len(screenshot),
            sha256=hashlib.sha256(screenshot).hexdigest(),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(output, screenshot)
        _atomic_write(manifest, (metadata.model_dump_json(indent=2) + "\n").encode("utf-8"))
    except (OSError, ValueError, Image.DecompressionBombError):
        raise CaptureError(
            "Could not save the screenshot and capture manifest. "
            "Check output access and use a smaller capture for oversized pages."
        ) from None
    return CaptureResult(screenshot_path=output, manifest_path=manifest, metadata=metadata)
