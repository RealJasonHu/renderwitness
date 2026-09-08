"""Security and evidence tests for the portable browser report.

Browser interaction checks supplement these tests in the release verification;
these tests inspect the generated artifact without a browser dependency.
"""

from __future__ import annotations

import base64
import io
import json
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image

from renderwitness.diff import compare_images
from renderwitness.models import AnalysisResult, BoundingBox, Finding
from renderwitness.report import render_html


class ReportDocument(HTMLParser):
    def __init__(self, document: str) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.scripts: list[str] = []
        self.structured_result = ""
        self._script = False
        self._json = False
        self.feed(document)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        if tag == "script":
            self._script = True
            self.scripts.append("")
        if attributes.get("id") == "structured-result":
            self._json = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._script = False
        if tag == "pre":
            self._json = False

    def handle_data(self, data: str) -> None:
        if self._script:
            self.scripts[-1] += data
        if self._json:
            self.structured_result += data

    @property
    def images(self) -> list[Image.Image]:
        images = []
        for tag, attributes in self.elements:
            if tag == "img":
                source = attributes["src"]
                assert source is not None and source.startswith("data:image/png;base64,")
                image = Image.open(io.BytesIO(base64.b64decode(source.split(",", 1)[1])))
                image.load()
                images.append(image)
        return images


def _result(baseline: Path, candidate: Path, **comparison_settings: object) -> AnalysisResult:
    comparison = compare_images(baseline, candidate, **comparison_settings)  # type: ignore[arg-type]
    return AnalysisResult(
        comparison=comparison,
        provider="fixture",
        summary="Review the attached pixel evidence.",
        verdict="review",
    )


def test_provider_payload_cannot_change_executable_report_content(
    image_pair: tuple[Path, Path],
) -> None:
    baseline, candidate = image_pair
    result = _result(baseline, candidate)
    normal = ReportDocument(render_html(result, baseline, candidate))
    attack = "</script><script>alert('injected')</script><img src=x onerror=alert(1)>"
    result.provider = attack
    result.model = attack
    result.prompt_version = attack
    result.summary = attack
    result.findings = [
        Finding(
            id="finding-1",
            region_id=result.comparison.regions[0].id,
            category=attack,
            title=attack,
            description=attack,
            suggestion=attack,
            severity="major",
            confidence=0.9,
        )
    ]
    malicious = ReportDocument(render_html(result, baseline, candidate))

    assert len(malicious.scripts) == 1
    assert malicious.scripts == normal.scripts
    assert len(malicious.images) == 3
    assert not any(key.startswith("on") for _, attrs in malicious.elements for key in attrs)
    assert json.loads(malicious.structured_result) == result.model_dump(mode="json")


def test_report_has_no_external_assets_and_json_remains_complete(
    image_pair: tuple[Path, Path],
) -> None:
    baseline, candidate = image_pair
    result = _result(baseline, candidate)
    document = render_html(result, baseline, candidate)
    parsed = ReportDocument(document)

    for tag, attrs in parsed.elements:
        assert tag not in {"link", "iframe", "object", "embed"}
        if "src" in attrs:
            assert tag == "img"
            assert (attrs["src"] or "").startswith("data:image/png;base64,")
        if "href" in attrs:
            assert (attrs["href"] or "").startswith("#")
    assert "url(" not in document
    assert "@import" not in document
    assert len(parsed.images) == 3
    assert json.loads(parsed.structured_result) == result.model_dump(mode="json")


def test_embedded_screenshots_match_exif_oriented_pixel_coordinates(tmp_path: Path) -> None:
    source = tmp_path / "portrait.jpg"
    image = Image.new("RGB", (20, 12), "#ff0000")
    image.paste("#0000ff", (10, 0, 20, 12))
    exif = image.getexif()
    exif[274] = 6  # Rotate 90 degrees clockwise when displayed.
    image.save(source, exif=exif, quality=100, subsampling=0)
    result = _result(source, source)

    parsed = ReportDocument(render_html(result, source, source))

    assert (result.comparison.width, result.comparison.height) == (12, 20)
    for embedded in parsed.images[:2]:
        assert embedded.size == (12, 20)
        assert embedded.mode == "RGB"
        assert not embedded.getexif()
        top = embedded.getpixel((6, 2))
        bottom = embedded.getpixel((6, 17))
        assert isinstance(top, tuple) and top[0] > 240 and top[2] < 10
        assert isinstance(bottom, tuple) and bottom[2] > 240 and bottom[0] < 10


def test_transparent_evidence_is_composited_over_white(tmp_path: Path) -> None:
    source = tmp_path / "transparent.png"
    image = Image.new("RGBA", (2, 1), (255, 0, 0, 0))
    image.putpixel((1, 0), (0, 0, 255, 128))
    image.save(source)
    result = _result(source, source)

    parsed = ReportDocument(render_html(result, source, source))

    for embedded in parsed.images[:2]:
        assert embedded.getpixel((0, 0)) == (255, 255, 255)
        assert embedded.getpixel((1, 0)) == (127, 127, 255)


def test_animated_evidence_embeds_only_the_measured_first_frame(tmp_path: Path) -> None:
    source = tmp_path / "animated.gif"
    first = Image.new("RGB", (3, 2), "red")
    second = Image.new("RGB", (3, 2), "blue")
    first.save(source, save_all=True, append_images=[second], duration=80, loop=0)
    result = _result(source, source)

    parsed = ReportDocument(render_html(result, source, source))

    for embedded in parsed.images[:2]:
        assert embedded.format == "PNG"
        assert getattr(embedded, "n_frames", 1) == 1
        assert embedded.getpixel((0, 0)) == (255, 0, 0)


def test_diff_map_respects_threshold_exclusions_and_compared_denominator(tmp_path: Path) -> None:
    baseline = tmp_path / "before.png"
    candidate = tmp_path / "after.png"
    before = Image.new("RGB", (4, 1), "white")
    after = before.copy()
    after.putpixel((0, 0), (0, 0, 0))
    after.putpixel((1, 0), (245, 245, 245))  # Below threshold.
    after.putpixel((2, 0), (0, 0, 0))  # Explicitly excluded.
    before.save(baseline)
    after.save(candidate)
    result = _result(
        baseline,
        candidate,
        threshold=24,
        min_region_area=1,
        ignore_regions=[BoundingBox(x=2, y=0, width=1, height=1)],
    )

    document = render_html(result, baseline, candidate)
    heatmap = ReportDocument(document).images[2]

    quiet = heatmap.getpixel((3, 0))
    assert heatmap.getpixel((0, 0)) != quiet
    assert heatmap.getpixel((1, 0)) == quiet
    assert heatmap.getpixel((2, 0)) == quiet
    assert result.comparison.changed_pixels == 1
    assert "of 3 compared pixels" in document
    assert "1 exclusions · 1 px" in document
