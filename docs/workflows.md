# Workflows

[README](../README.md) · [CI policy](ci.md) · [Example fixtures](../examples/README.md)

## Choose an entry point

| Input | Command | Output |
|---|---|---|
| No screenshots yet | `renderwitness demo -o reports/demo` | Bundled synthetic screenshots and a review report |
| One screenshot pair | `renderwitness compare before.png after.png -o reports/change` | Comparison evidence, HTML/JSON review, gate decision |
| Several screenshot pairs | `renderwitness suite suite.json -o reports/run-001` | Per-case evidence and suite summaries |
| A web page | `renderwitness capture URL -o screenshot.png` | PNG and capture metadata |

The default provider is `demo`: a deterministic pixel heuristic with no model or network call.
Use `--provider openai-compatible` for actual vision-model analysis.

## Capture a stable page

Install the optional dependency and browser:

```bash
python -m pip install -e '.[capture]'
python -m playwright install chromium
```

Start your application, then capture baseline and candidate with identical settings:

```bash
renderwitness capture http://localhost:8000/ \
  --output screenshots/baseline.png \
  --width 1440 --height 900 --locale zh-CN \
  --color-scheme light \
  --wait-for '[data-renderwitness-ready="true"]' \
  --mask '[data-testid="clock"]'
```

This produces `screenshots/baseline.png` and `screenshots/baseline.capture.json`.
The sidecar records browser version, viewport and options, dimensions, timestamp, byte size, and
screenshot SHA-256. URL credentials, query strings, and fragments are omitted from that metadata;
URL paths, selector strings, and screenshot pixels remain.

| Capture option | Default | Behavior |
|---|---|---|
| `--width`, `--height` | `1280`, `800` | CSS-pixel viewport; each dimension is limited to 8192 |
| `--locale` | `en-US` | Browser locale; does not rewrite application content |
| `--color-scheme` | `light` | `light`, `dark`, or `no-preference` |
| `--wait-for` | None | Wait for the selector to be visible |
| `--mask` | None | Repeat for each selector to cover in the captured PNG |
| `--full-page` | Off | Capture the entire page instead of the viewport |
| `--timeout-ms` | `30000` | Per-operation browser timeout, up to `300000` |

Each capture starts a fresh headless Chromium context with device scale factor 1, UTC timezone,
reduced motion, blocked service workers, disabled screenshot animations, and a hidden caret.
It waits for page load, the optional readiness selector, and font readiness. A requested mask
selector must be present; a missing selector causes an error instead of silently omitting the mask.
Masked elements are painted purple in the saved PNG.

These controls reduce variation; they do not freeze JavaScript clocks, API responses, randomized
content, or lazy loading. Provide deterministic application data and a readiness marker. Keep
browser versions, operating-system fonts, and viewport settings consistent. Full-page screenshots
can differ in height when content changes; the comparison will reject unequal dimensions.

Only HTTP, HTTPS, and local file URLs are accepted. HTTP error responses are rejected. This
command does not perform login, clicks, scrolling sequences, or baseline/candidate server startup.
Use your existing browser tests for those flows, then pass their screenshots to `compare`.

## Tune a comparison

```bash
renderwitness compare baseline.png candidate.png \
  --threshold 24 \
  --min-region-area 16 \
  --max-regions 20 \
  --grouping-distance 8 \
  --region-padding 24 \
  --output reports/change
```

| Option | Meaning |
|---|---|
| `--threshold` | A pixel changes when its largest absolute RGB-channel delta is strictly greater than this value (0–255) |
| `--min-region-area` | Minimum changed-pixel count for a retained region, despite the historical option name |
| `--max-regions` | Keep up to this many regions, ordered by changed-pixel count and then mean delta |
| `--grouping-distance` | Controls approximate grouping of nearby changes on a bounded grid |
| `--region-padding` | Add context around each retained region, clipped to image bounds |
| `--max-image-mb` | Per-input file-size limit in MiB; default 25 |
| `--max-pixels` | Per-input decoded-pixel limit; default 40,000,000 |

Start by fixing inconsistent capture conditions. Then inspect the paired and diff views before
changing thresholds. A higher threshold suppresses subtle color changes; a larger minimum region
size hides small regions. Neither should be used to explain away a known defect.

Filtering or truncating regions does not remove their changed pixels from the global ratio.
A report can therefore have a nonzero changed-pixel count and no retained regions. Region padding
can make boxes overlap; adding all region pixel counts is not a valid global total.

## Ignore dynamic content

```bash
renderwitness compare baseline.png candidate.png \
  --ignore-region 1200,0,240,64 \
  --ignore-region 40,820,300,40 \
  --output reports/change
```

Rectangles use `x,y,width,height` in screenshot pixels, with exclusive right and bottom edges.
Origins must be nonnegative, sizes positive, and rectangles entirely inside the image. Overlapping
rectangles are counted once. A mask that excludes the entire image is rejected.

The global ratio is:

```text
change_ratio = changed nonignored pixels / (total pixels - ignored pixels)
```

Use `capture --mask SELECTOR` when the content should be covered in the actual captured PNG.
Use `compare --ignore-region` when the pixels should remain available for human review but be
excluded from diff statistics. The built-in model adapter also covers those rectangles in its
normalized input images. An ignore rectangle is not report redaction: full originals remain
in the HTML report. A custom provider controls its own image handling.

## Author a suite

Create `suite.json` next to your image directory:

```json
{
  "version": 1,
  "name": "Localized checkout",
  "defaults": {
    "threshold": 24,
    "min_region_area": 16,
    "region_padding": 24
  },
  "policy": {
    "max_change_ratio": 0.01,
    "fail_on_severity": null,
    "min_confidence": 0.8,
    "fail_on_review": false
  },
  "scenarios": [
    {
      "id": "desktop-zh",
      "name": "Chinese desktop checkout",
      "baseline": "images/desktop-zh-before.png",
      "candidate": "images/desktop-zh-after.png",
      "ignore_regions": [{"x": 1200, "y": 0, "width": 240, "height": 64}]
    },
    {
      "id": "mobile-en",
      "baseline": "images/mobile-en-before.png",
      "candidate": "images/mobile-en-after.png",
      "diff": {"threshold": 30},
      "policy": {"max_change_ratio": 0.02}
    }
  ]
}
```

Run it into a new or empty directory:

```bash
renderwitness suite suite.json --provider demo --output reports/run-001
```

The configuration is JSON, not YAML; its [JSON Schema](../schemas/suite.schema.json) is checked in
for editor validation. Unknown fields are rejected. It accepts 1–1000 scenarios,
and IDs must be unique regardless of case, start with a letter or digit, and contain only letters,
digits, underscores, or hyphens. Paths are resolved relative to the configuration file.

Top-level `defaults` accepts the diff options listed above, using underscore names. For the file
limit, use `max_image_bytes` rather than the CLI's `--max-image-mb`. Scenario `diff` and `policy`
objects override only explicitly provided fields. For nullable policy thresholds,
`null` removes an inherited rule. Ignore rectangles are configured per scenario.

Suites compare already-captured images sequentially. They do not execute browser capture, expand
viewport matrices, or run the legacy `examples/scenarios.yaml` design sketch.
Reusing a nonempty suite output is rejected to prevent stale artifacts from appearing in a later
run. Output must not contain the configuration or source images.

## Read the result

Open `index.html` for screenshot and finding review. Compare the screenshots in split, blend,
or diff mode, then filter findings by severity. Check the measured change ratio
separately from the provider's assessment.

A single comparison replaces stale result files with incomplete-run markers before starting.
It writes `comparison.json` before model analysis, then `report.json`,
`index.html`, and `gate.json`. If model analysis fails after the diff succeeds, the command
attempts an explicitly labeled fallback report with deterministic evidence and returns exit code 2.
Invalid images cannot produce a comparison report, and storage failures may prevent artifact writes.

A suite adds a report directory per case plus HTML, JSON, Markdown, and JUnit summaries.
See [CI integration](ci.md) for gate interpretation and error handling.

## Use the Python library

The same components can be called from a test runner without invoking the CLI:

```python
from renderwitness.analyzer import compare_and_analyze
from renderwitness.policy import GatePolicy, evaluate_policy
from renderwitness.report import write_report

result = compare_and_analyze("baseline.png", "candidate.png", threshold=24)
paths = write_report(result, "baseline.png", "candidate.png", "reports/library")
gate = evaluate_policy(result, GatePolicy(max_change_ratio=0.01))

print(paths.html)
print(gate.passed, gate.reasons)
```

This uses the deterministic demo provider. Pass a `VisionProvider` instance with `provider=`
to use a configured model. The library functions raise typed errors; they do not automatically
write fallback reports or set the process exit status. Your test runner controls that behavior.
For browser capture, see the [capture API guide](capture.md).
