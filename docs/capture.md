# Reproducible browser capture

RenderWitness can capture a URL before comparing images. Chromium capture is an
optional dependency; comparing existing images still works without a browser.

```bash
pip install 'renderwitness[capture]'
python -m playwright install chromium
```

The API supports HTTP, HTTPS and local `file://` URLs. A fresh unauthenticated
browser context is created for every capture. It does not reuse your personal
browser, cookies, local storage or login state.

```python
from pathlib import Path

from renderwitness.capture import CaptureOptions, capture_page
from renderwitness.diff import compare_images

fixtures = Path("examples/web").resolve()
options = CaptureOptions(
    width=390,
    height=844,
    locale="zh-CN",
    wait_for="main",
    mask_selectors=("#live-clock",),
)
baseline = capture_page(
    (fixtures / "baseline.html").as_uri(), "artifacts/baseline.png", options=options
)
candidate = capture_page(
    (fixtures / "candidate.html").as_uri(), "artifacts/candidate.png", options=options
)
comparison = compare_images(baseline.screenshot_path, candidate.screenshot_path)
print(comparison.change_ratio)
print(baseline.manifest_path)
```

`capture_page(url, output_path, *, options=None)` returns a validated
`CaptureResult` with `screenshot_path`, `manifest_path`, and `metadata`. Output
paths must end in `.png`; the adjacent manifest uses `.capture.json`.

## Controls and defaults

| Option | Default | Purpose |
| --- | --- | --- |
| `width`, `height` | `1280`, `800` | CSS viewport pixels, each between 1 and 8192 |
| `locale` | `en-US` | Browser locale and language header |
| `color_scheme` | `light` | `light`, `dark`, or `no-preference` |
| `reduced_motion` | `reduce` | `reduce` or `no-preference` |
| `timeout_ms` | `30000` | Per-operation timeout, between 1 and 300000 ms |
| `full_page` | `False` | Capture viewport; `True` captures the whole scrollable page |
| `wait_for` | `None` | Wait for one selector to become visible after page load |
| `mask_selectors` | `()` | Cover matching elements with solid purple rectangles |

Every capture uses UTC, a device scale of 1, disabled screenshot animations, a
hidden caret, blocked service workers, and a font-readiness wait. The page itself
still executes its normal JavaScript. RenderWitness's only injected evaluation
waits for `document.fonts.ready` with a timeout. No generic script injection or
interaction hook is exposed.

Use the same options for baseline and candidate. Keep browser versions, OS fonts
and application data consistent in CI: these settings reduce nondeterminism but
cannot make arbitrary live sites perfectly deterministic. A ticking clock,
random data, canvas drawing, delayed application updates or an animated image may
still vary. Mask changing areas or use fixed application fixtures. `wait_for`
should identify an application-ready element when initial page load is too early.

All mask selectors must match at least one attached element. An absent selector
fails the capture instead of silently omitting a mask. Playwright applies masks
to all matching elements, including invisible matches; use selectors scoped to
the content you intend to exclude. Masking changes the evidence, so the manifest
records every selector and both images should use the same masks.

`full_page=True` can produce different dimensions when a regression changes page
height or width. The image comparator requires equal dimensions. The default
viewport capture makes clipping and overflow observable within a fixed frame.

## Provenance and failure behavior

The JSON manifest records the source and final URL, capture time, Chromium
version, all capture options, effective screenshot dimensions, byte size and
SHA-256. It strips URL username/password, the complete query string, and fragment
from both URLs. Browser exception text is omitted from `CaptureError` messages
because it can contain full URLs and credentials.

URL paths, selectors, local filenames and screenshot pixels are retained. Do not
place secrets in paths or selectors, and mask private page content before sharing
artifacts. The manifest is capture provenance, not a proof that a page is correct.

HTTP status 400 and above, selector failures, font timeouts and screenshot
failures abort the capture. Browser contexts and the browser are closed on both
success and failure. Existing outputs are preserved on browser failures. After
success, PNG and manifest files are each replaced atomically; the pair is not a
single atomic filesystem transaction. A disk failure can leave the pair out of
sync, which is detectable using the manifest SHA-256.

This is a synchronous API. Applications already running an asyncio event loop
should call it in a worker thread, for example with `asyncio.to_thread`. The
timeout is per operation; it is not a total wall-clock deadline.

## Local browser verification

The test suite uses mocked browsers by default. To run the real Chromium fixture
check after installing the browser:

```bash
RENDERWITNESS_BROWSER_TESTS=1 pytest tests/test_capture.py
```

That check captures the masked mobile baseline twice and requires identical
image hashes, then compares the deliberately broken candidate and checks that
changed regions exist. See [the fixture guide](../examples/web/README.md) for the
seeded issues and their expected meaning.

Capture behavior follows the official Playwright [screenshot API](https://playwright.dev/python/docs/api/class-page#page-screenshot)
and [browser context options](https://playwright.dev/python/docs/api/class-browser#browser-new-context).
