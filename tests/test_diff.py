from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from renderwitness.diff import ComparisonError, ImageSafetyError, compare_images


def bbox_contains(region: object, x: int, y: int) -> bool:
    bbox = region.bbox
    return bbox.x <= x < bbox.x + bbox.width and bbox.y <= y < bbox.y + bbox.height


def test_compare_images_returns_measured_and_localized_evidence(
    image_pair: tuple[Path, Path],
) -> None:
    baseline, candidate = image_pair

    result = compare_images(
        baseline,
        candidate,
        threshold=10,
        min_region_area=4,
        max_regions=10,
    )

    assert result.identical is False
    assert result.width == 96
    assert result.height == 72
    assert result.total_pixels == 96 * 72
    assert result.changed_pixels == (20 * 16) + (14 * 14)
    assert result.change_ratio == pytest.approx(result.changed_pixels / result.total_pixels)
    assert len(result.regions) == 2
    assert [region.id for region in result.regions] == ["region-001", "region-002"]
    assert any(bbox_contains(region, 12, 10) for region in result.regions)
    assert any(bbox_contains(region, 81, 61) for region in result.regions)
    assert all(0 < region.pixel_ratio <= 1 for region in result.regions)
    assert all(region.changed_pixels <= region.area for region in result.regions)
    assert result.baseline.sha256 != result.candidate.sha256


def test_identical_pair_has_no_regions(tmp_path: Path) -> None:
    path = tmp_path / "same.png"
    Image.new("RGBA", (30, 20), (240, 240, 240, 255)).save(path)

    result = compare_images(path, path)

    assert result.identical is True
    assert result.changed_pixels == 0
    assert result.change_ratio == 0
    assert result.regions == []
    assert result.baseline.sha256 == result.candidate.sha256


def test_threshold_filters_small_per_channel_noise(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (32, 32), (100, 100, 100)).save(baseline)
    noisy = Image.new("RGB", (32, 32), (100, 100, 100))
    ImageDraw.Draw(noisy).rectangle((5, 5, 20, 20), fill=(112, 112, 112))
    noisy.save(candidate)

    ignored = compare_images(baseline, candidate, threshold=20, min_region_area=1)
    detected = compare_images(baseline, candidate, threshold=5, min_region_area=1)

    assert ignored.identical is True
    assert detected.identical is False
    assert detected.changed_pixels == 16 * 16


def test_region_limit_is_deterministic(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (100, 40), "white").save(baseline)
    changed = Image.new("RGB", (100, 40), "white")
    draw = ImageDraw.Draw(changed)
    for left in (4, 28, 52, 76):
        draw.rectangle((left, 8, left + 7, 15), fill="black")
    changed.save(candidate)

    first = compare_images(baseline, candidate, min_region_area=1, max_regions=2)
    second = compare_images(baseline, candidate, min_region_area=1, max_regions=2)

    assert len(first.regions) == 2
    assert first.regions == second.regions


def test_mismatched_dimensions_fail_before_diffing(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (20, 20), "white").save(baseline)
    Image.new("RGB", (21, 20), "white").save(candidate)

    with pytest.raises(ComparisonError, match="dimension|size|match"):
        compare_images(baseline, candidate)


def test_untrusted_or_oversized_inputs_are_rejected(
    tmp_path: Path,
    make_image_pair: Callable[[tuple[int, int], tuple[int, int, int, int]], tuple[Path, Path]],
) -> None:
    invalid = tmp_path / "not-an-image.png"
    invalid.write_text("this is not image data", encoding="utf-8")
    _, valid = make_image_pair((20, 20), (2, 2, 8, 8))

    with pytest.raises(ImageSafetyError):
        compare_images(invalid, valid)

    baseline, candidate = make_image_pair((40, 40), (2, 2, 8, 8))
    with pytest.raises(ImageSafetyError, match="byte|large|size"):
        compare_images(baseline, candidate, max_image_bytes=1)
    with pytest.raises(ImageSafetyError, match="pixel|large|size"):
        compare_images(baseline, candidate, max_pixels=100)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"threshold": -1}, "threshold"),
        ({"threshold": 256}, "threshold"),
        ({"min_region_area": 0}, "min_region_area"),
        ({"max_regions": 0}, "max_regions"),
        ({"max_regions": 201}, "max_regions"),
        ({"grouping_distance": -1}, "grouping_distance"),
        ({"grouping_distance": 129}, "grouping_distance"),
        ({"region_padding": -1}, "region_padding"),
        ({"region_padding": 257}, "region_padding"),
        ({"max_image_bytes": 0}, "safety limits"),
        ({"max_pixels": 0}, "safety limits"),
    ],
)
def test_diff_configuration_is_bounded_before_reading_files(
    kwargs: dict[str, int], message: str
) -> None:
    with pytest.raises(ComparisonError, match=message):
        compare_images("never-read-a.png", "never-read-b.png", **kwargs)


@pytest.mark.parametrize("kind", ["missing", "directory", "empty"])
def test_non_regular_input_paths_have_clear_errors(tmp_path: Path, kind: str) -> None:
    source = tmp_path / "input.png"
    if kind == "directory":
        source.mkdir()
    elif kind == "empty":
        source.touch()

    with pytest.raises(ComparisonError, match="Cannot read|regular file|empty"):
        compare_images(source, source)


def test_region_padding_adds_bounded_visual_context(
    make_image_pair: Callable[[tuple[int, int], tuple[int, int, int, int]], tuple[Path, Path]],
) -> None:
    baseline, candidate = make_image_pair((40, 30), (1, 2, 5, 7))

    result = compare_images(
        baseline,
        candidate,
        min_region_area=1,
        grouping_distance=0,
        region_padding=4,
    )

    assert len(result.regions) == 1
    assert result.regions[0].bbox.model_dump() == {
        "x": 0,
        "y": 0,
        "width": 10,
        "height": 12,
    }


def test_changed_pixels_can_be_retained_without_any_roi(
    make_image_pair: Callable[[tuple[int, int], tuple[int, int, int, int]], tuple[Path, Path]],
) -> None:
    baseline, candidate = make_image_pair((30, 30), (4, 4, 5, 5))

    result = compare_images(
        baseline,
        candidate,
        min_region_area=10,
        grouping_distance=0,
        region_padding=0,
    )

    assert result.changed_pixels == 4
    assert result.identical is False
    assert result.regions == []
