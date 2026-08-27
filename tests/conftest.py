from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


@pytest.fixture
def image_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Return a small pair with two separated, deterministic changes."""
    baseline_path = tmp_path / "baseline.png"
    candidate_path = tmp_path / "candidate.png"

    baseline = Image.new("RGB", (96, 72), "white")
    candidate = baseline.copy()
    draw = ImageDraw.Draw(candidate)
    draw.rectangle((12, 10, 31, 25), fill="#101828")
    draw.rectangle((68, 48, 81, 61), fill="#6D5CE7")
    baseline.save(baseline_path)
    candidate.save(candidate_path)
    return baseline_path, candidate_path


@pytest.fixture
def make_image_pair(
    tmp_path: Path,
) -> Callable[[tuple[int, int], tuple[int, int, int, int]], tuple[Path, Path]]:
    """Create a pair with a single changed inclusive Pillow rectangle."""

    def factory(
        size: tuple[int, int] = (64, 48),
        changed_box: tuple[int, int, int, int] = (8, 9, 23, 20),
    ) -> tuple[Path, Path]:
        baseline_path = tmp_path / "base.png"
        candidate_path = tmp_path / "candidate.png"
        baseline = Image.new("RGB", size, "white")
        candidate = baseline.copy()
        ImageDraw.Draw(candidate).rectangle(changed_box, fill="black")
        baseline.save(baseline_path)
        candidate.save(candidate_path)
        return baseline_path, candidate_path

    return factory
