"""Safe, deterministic screenshot comparison and ROI extraction."""

from __future__ import annotations

import hashlib
import math
import warnings
from collections import deque
from collections.abc import Sequence
from pathlib import Path

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageFilter,
    ImageOps,
    ImageStat,
    UnidentifiedImageError,
)

from .models import BoundingBox, ComparisonResult, DiffRegion, ImageInfo

DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_PIXELS = 40_000_000
DEFAULT_MAX_REGIONS = 20
_MAX_GRID_CELLS = 1_000_000


class ComparisonError(ValueError):
    """Raised when two images cannot be meaningfully compared."""


class ImageSafetyError(ComparisonError):
    """Raised when an input exceeds configured resource limits."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_image(
    source: str | Path,
    *,
    max_image_bytes: int,
    max_pixels: int,
) -> tuple[Image.Image, ImageInfo]:
    path = Path(source).expanduser()
    try:
        stat = path.stat()
    except OSError as exc:
        raise ComparisonError(f"Cannot read image '{path}': {exc.strerror or exc}") from exc
    if not path.is_file():
        raise ComparisonError(f"Image path is not a regular file: {path}")
    if stat.st_size <= 0:
        raise ComparisonError(f"Image is empty: {path}")
    if stat.st_size > max_image_bytes:
        raise ImageSafetyError(
            f"Image '{path.name}' is {stat.st_size:,} bytes; "
            f"the configured limit is {max_image_bytes:,} bytes"
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as opened:
                width, height = opened.size
                if width <= 0 or height <= 0:
                    raise ComparisonError(f"Image has invalid dimensions: {path}")
                if width * height > max_pixels:
                    raise ImageSafetyError(
                        f"Image '{path.name}' has {width * height:,} pixels; "
                        f"the configured limit is {max_pixels:,}"
                    )
                image_format = (opened.format or path.suffix.lstrip(".") or "unknown").upper()
                original_mode = opened.mode
                opened.seek(0)
                opened.load()
                oriented = ImageOps.exif_transpose(opened)
                if oriented is None:  # Defensive guard for Pillow's in-place overload.
                    raise ComparisonError(f"Could not orient image: {path}")
                rgba = oriented.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                rgb = Image.alpha_composite(background, rgba).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageSafetyError(f"Unsupported or corrupt image '{path}': {exc}") from exc
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageSafetyError(f"Image '{path.name}' triggered Pillow's safety limit") from exc

    info = ImageInfo(
        path=str(path.resolve()),
        filename=path.name,
        width=rgb.width,
        height=rgb.height,
        mode=original_mode,
        format=image_format,
        byte_size=stat.st_size,
        sha256=_sha256(path),
    )
    return rgb, info


def _pixel_mask(difference: Image.Image, threshold: int) -> tuple[Image.Image, Image.Image]:
    red, green, blue = difference.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    mask = maximum.point(lambda value: 255 if value > threshold else 0, mode="L")
    return maximum, mask


def _component_boxes(mask: Image.Image, grouping_distance: int) -> list[tuple[int, int, int, int]]:
    """Find approximate connected components on a bounded-size occupancy grid."""

    width, height = mask.size
    tile = max(1, math.ceil(math.sqrt((width * height) / _MAX_GRID_CELLS)))
    grid_width = math.ceil(width / tile)
    grid_height = math.ceil(height / tile)
    grid = mask.resize((grid_width, grid_height), Image.Resampling.BOX)
    grid = grid.point(lambda value: 255 if value else 0, mode="L")

    radius = math.ceil(grouping_distance / tile)
    if radius:
        # Pillow requires an odd kernel; cap it to keep comparison cost predictable.
        kernel = min(9, radius * 2 + 1)
        grid = grid.filter(ImageFilter.MaxFilter(kernel))

    data = bytearray(grid.tobytes())
    boxes: list[tuple[int, int, int, int]] = []
    neighbors = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))

    for start in range(len(data)):
        if data[start] == 0:
            continue
        data[start] = 0
        queue: deque[int] = deque([start])
        start_y, start_x = divmod(start, grid_width)
        min_x = max_x = start_x
        min_y = max_y = start_y
        while queue:
            current = queue.popleft()
            y, x = divmod(current, grid_width)
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for dx, dy in neighbors:
                nx, ny = x + dx, y + dy
                if 0 <= nx < grid_width and 0 <= ny < grid_height:
                    index = ny * grid_width + nx
                    if data[index]:
                        data[index] = 0
                        queue.append(index)

        left = max(0, min_x * tile)
        top = max(0, min_y * tile)
        right = min(width, (max_x + 1) * tile)
        bottom = min(height, (max_y + 1) * tile)
        original = mask.crop((left, top, right, bottom)).getbbox()
        if original is not None:
            boxes.append(
                (
                    left + original[0],
                    top + original[1],
                    left + original[2],
                    top + original[3],
                )
            )
    return boxes


def _region_from_box(
    box: tuple[int, int, int, int],
    mask: Image.Image,
    maximum_delta: Image.Image,
) -> DiffRegion | None:
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None
    region_mask = mask.crop(box)
    histogram = region_mask.histogram()
    changed_pixels = sum(histogram[1:])
    if changed_pixels <= 0:
        return None
    delta_crop = maximum_delta.crop(box)
    stats = ImageStat.Stat(delta_crop, mask=region_mask)
    area = width * height
    return DiffRegion(
        id="pending",
        bbox=BoundingBox(x=left, y=top, width=width, height=height),
        area=area,
        changed_pixels=changed_pixels,
        pixel_ratio=changed_pixels / area,
        mean_delta=float(stats.mean[0]),
        max_delta=int(stats.extrema[0][1]),
    )


def _expand_box(
    box: tuple[int, int, int, int],
    *,
    padding: int,
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Add bounded visual context around a raw changed-pixel component."""

    left, top, right, bottom = box
    image_width, image_height = image_size
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(image_width, right + padding),
        min(image_height, bottom + padding),
    )


def compare_images(
    baseline: str | Path,
    candidate: str | Path,
    *,
    threshold: int = 24,
    min_region_area: int = 16,
    max_regions: int = DEFAULT_MAX_REGIONS,
    grouping_distance: int = 8,
    region_padding: int = 24,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    ignore_regions: Sequence[BoundingBox] = (),
) -> ComparisonResult:
    """Compare two screenshots and return bounded, structured diff regions.

    ``threshold`` is the required per-channel delta (0-255). ``min_region_area``
    is the minimum number of changed pixels retained as an ROI. Inputs must have
    equal post-orientation dimensions so an accidental viewport change is explicit.
    """

    if not 0 <= threshold <= 255:
        raise ComparisonError("threshold must be between 0 and 255")
    if min_region_area < 1:
        raise ComparisonError("min_region_area must be at least 1")
    if not 1 <= max_regions <= 200:
        raise ComparisonError("max_regions must be between 1 and 200")
    if not 0 <= grouping_distance <= 128:
        raise ComparisonError("grouping_distance must be between 0 and 128")
    if not 0 <= region_padding <= 256:
        raise ComparisonError("region_padding must be between 0 and 256")
    if max_image_bytes < 1 or max_pixels < 1:
        raise ComparisonError("image safety limits must be positive")

    baseline_image, baseline_info = _load_image(
        baseline, max_image_bytes=max_image_bytes, max_pixels=max_pixels
    )
    candidate_image, candidate_info = _load_image(
        candidate, max_image_bytes=max_image_bytes, max_pixels=max_pixels
    )
    if baseline_image.size != candidate_image.size:
        raise ComparisonError(
            "Image dimensions differ after orientation: "
            f"baseline is {baseline_image.width}x{baseline_image.height}, "
            f"candidate is {candidate_image.width}x{candidate_image.height}. "
            "Capture both screenshots at the same viewport."
        )

    difference = ImageChops.difference(baseline_image, candidate_image)
    maximum_delta, mask = _pixel_mask(difference, threshold)
    if len(ignore_regions) > 200:
        raise ComparisonError("At most 200 ignored regions are allowed")
    ignored = Image.new("L", baseline_image.size, 0)
    ignored_draw = ImageDraw.Draw(ignored)
    for ignored_box in ignore_regions:
        if ignored_box.right > baseline_image.width or ignored_box.bottom > baseline_image.height:
            raise ComparisonError("Ignored region exceeds screenshot dimensions")
        ignored_draw.rectangle(
            (ignored_box.x, ignored_box.y, ignored_box.right - 1, ignored_box.bottom - 1), fill=255
        )
    ignored_pixels = ignored.histogram()[255]
    if ignored_pixels == baseline_image.width * baseline_image.height:
        raise ComparisonError("Ignored regions must leave at least one pixel to compare")
    mask = ImageChops.subtract(mask, ignored)
    histogram = mask.histogram()
    changed_pixels = sum(histogram[1:])
    total_pixels = baseline_image.width * baseline_image.height

    regions: list[DiffRegion] = []
    if changed_pixels:
        for box in _component_boxes(mask, grouping_distance):
            padded_box = _expand_box(
                box,
                padding=region_padding,
                image_size=(baseline_image.width, baseline_image.height),
            )
            region = _region_from_box(padded_box, mask, maximum_delta)
            if region is not None and region.changed_pixels >= min_region_area:
                regions.append(region)
        regions.sort(
            key=lambda item: (
                -item.changed_pixels,
                -item.mean_delta,
                item.bbox.y,
                item.bbox.x,
            )
        )
        regions = [
            region.model_copy(update={"id": f"region-{index:03d}"})
            for index, region in enumerate(regions[:max_regions], start=1)
        ]

    return ComparisonResult(
        baseline=baseline_info,
        candidate=candidate_info,
        width=baseline_image.width,
        height=baseline_image.height,
        threshold=threshold,
        min_region_area=min_region_area,
        max_regions=max_regions,
        grouping_distance=grouping_distance,
        region_padding=region_padding,
        changed_pixels=changed_pixels,
        total_pixels=total_pixels,
        ignored_regions=list(ignore_regions),
        ignored_pixels=ignored_pixels,
        change_ratio=changed_pixels / (total_pixels - ignored_pixels),
        identical=changed_pixels == 0,
        regions=regions,
    )
