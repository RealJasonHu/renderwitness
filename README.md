<div align="center">
  <img src="docs/assets/workbench.png" alt="Actual RenderWitness report from captured browser fixtures, showing pixel evidence and metric-only findings" width="100%" />
</div>

<p align="center">Generated from the local browser fixture with the offline demo provider. No VLM call was made.</p>

<p align="center">
  <a href="README.zh-CN.md">中文</a> ·
  <a href="docs/workflows.md">Workflows</a> ·
  <a href="docs/ci.md">CI integration</a> ·
  <a href="docs/architecture.md">Architecture</a>
</p>

# RenderWitness

**Capture screenshots, locate visual changes, and review the evidence before a release.**

RenderWitness is a Python CLI and library for screenshot regression review. It combines deterministic
pixel comparison with optional vision-language model (VLM) analysis, then packages the screenshots,
changed regions, findings, and run metadata into a portable report.

Use it to investigate a changed UI, run screenshot suites in CI, or add visual evidence to an
existing test pipeline. Browser capture is optional; screenshots from another test runner or a
desktop application work too.

## What is included

| Capability | What you get |
|---|---|
| Screenshot comparison | Thresholded RGB differences, bounded regions, source hashes, and image limits |
| Noise control | Region grouping and padding, plus rectangles excluded from diff metrics |
| Browser capture | Optional Playwright Chromium capture with viewport, locale, readiness selector, and masks |
| Scenario suites | Strict JSON configuration, per-case overrides, continued execution after case errors |
| CI gates | Changed-pixel budget, severity and confidence thresholds, and review handling |
| Review reports | Side-by-side, blend, and diff views, severity filters, HTML and structured JSON |
| Suite exports | Navigable HTML index, JSON summary, Markdown summary, and JUnit XML |
| Model adapters | Network-free metric-only demo or an OpenAI-compatible vision endpoint |

Pixel comparison measures rendering changes. Model findings suggest what those changes mean;
they do not replace screenshot review. The `demo` provider never calls a VLM and does not detect
semantic defects such as clipped text.

## Start with the offline demo

From a checkout of this repository, using Python 3.11 or later:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

renderwitness demo --output reports/demo
```

Open the printed HTML path in a browser. After installation, the demo needs no API key, network,
GPU, or model download. Its synthetic bilingual dashboard contains intentional visual changes;
the provider reports only measurable pixel differences.

## Compare two screenshots

```bash
renderwitness compare examples/baseline.png examples/candidate.png \
  --provider demo \
  --output reports/my-change
```

The images must have equal dimensions after orientation. PNG, JPEG, WebP, and GIF are supported
throughout the report pipeline. Animated images are compared using their first frame.

To exclude a known dynamic region and enforce a 1% changed-pixel budget:

```bash
renderwitness compare baseline.png candidate.png \
  --ignore-region 1200,0,240,64 \
  --max-change-ratio 0.01 \
  --output reports/release
```

The rectangle uses screenshot pixels (`x,y,width,height`) and must fit inside both images.
The ratio counts only nonignored pixels. Ignored areas are also masked in model inputs, but
**original images remain visible in reports**. See [workflow details](docs/workflows.md#ignore-dynamic-content).

## Run a scenario suite

```bash
renderwitness suite examples/suite.json --provider demo --output reports/suite
```

A suite requires a new or empty output directory. This bundled example intentionally returns
exit code 1: an unchanged control passes, the seeded regression fails, and a review-only case passes.

A suite compares existing screenshots. Image paths are relative to the configuration file:

```json
{
  "version": 1,
  "name": "Release screenshots",
  "defaults": { "threshold": 24 },
  "policy": { "max_change_ratio": 0.01 },
  "scenarios": [
    {
      "id": "overview-desktop",
      "name": "Overview at desktop width",
      "baseline": "baseline.png",
      "candidate": "candidate.png"
    }
  ]
}
```

Outputs include `index.html`, `summary.json`, `summary.md`, `junit.xml`, and individual case reports.
A failed case does not prevent later cases from running. The provider verdict and CI gate result
are separate: the gate fails only when a configured rule is violated.

| Exit code | Meaning |
|---|---|
| `0` | Execution completed and configured gates passed |
| `1` | Execution completed, but at least one configured gate failed |
| `2` | Configuration, input, capture, provider, or report error; takes precedence over gate failures |

See [CI integration](docs/ci.md) for policy semantics and artifact retention.

## Capture a browser page

Install the optional browser dependency and Chromium once:

```bash
python -m pip install -e '.[capture]'
python -m playwright install chromium

renderwitness capture http://localhost:8000/ \
  --output screenshot.png \
  --width 1440 --height 900 --locale zh-CN \
  --wait-for '[data-renderwitness-ready="true"]'
```

Use the same browser environment, fonts, viewport, and capture settings for both screenshots.
The repository includes a [bilingual browser fixture](examples/README.md) with intentional
regressions for trying the complete capture → compare → review workflow.

Run the complete local browser example after installing Chromium:

```bash
python scripts/run_browser_demo.py --output reports/browser-demo
```

The script checks two intentionally failing regression cases and an unchanged passing control.
It returns 0 when those expected outcomes are verified. Open `reports/browser-demo/review/index.html`.

## Add real model analysis

Connect a vision model that accepts the OpenAI-compatible Chat Completions image contract.
Replace the example model name with a model installed on your local server:

```bash
export RENDERWITNESS_BASE_URL=http://localhost:11434/v1
export RENDERWITNESS_MODEL=your-vision-model
export RENDERWITNESS_API_KEY=ollama

renderwitness compare examples/baseline.png examples/candidate.png \
  --provider openai-compatible \
  --output reports/model-review
```

The adapter sends normalized screenshots with ignored areas masked, plus region metadata. It validates returned JSON and checks
region references. A finding may explicitly have no region reference. Validation confirms the
expected structure; it does not establish that the interpretation is correct.

See the [model guide](docs/model-guide.md) for endpoint requirements, data handling, and failure
behavior. Real-model accuracy has not been established by the offline demo or CI tests.

## How it fits together

```text
URL → optional Chromium capture → screenshots
                                      │
baseline + candidate → validated image pair
                              │
                    pixel diff + ignore regions
                              │
                    bounded visual evidence
                              │
               demo metrics / optional VLM review
                              │
                     structured validation
                              │
               HTML + JSON → explicit CI policy
                              │
                 suite index / Markdown / JUnit
```

## Documentation

| Guide | Start here when you want to… |
|---|---|
| [Workflows](docs/workflows.md) | Tune comparisons, capture pages, or author a suite |
| [Browser capture](docs/capture.md) | Use the Python capture API and inspect capture provenance |
| [CI integration](docs/ci.md) | Configure gates and keep reports from failing runs |
| [Architecture](docs/architecture.md) | Understand the algorithm, contracts, and tradeoffs |
| [Model guide](docs/model-guide.md) | Connect and evaluate a real vision model |
| [Examples](examples/README.md) | Reproduce screenshot and browser fixtures |
| [Contributing](CONTRIBUTING.md) | Set up development and validate a change |
| [Changelog](CHANGELOG.md) | See versioned changes |
| [Security](SECURITY.md) | Report vulnerabilities and understand data considerations |

## Development

```bash
python -m pip install -e '.[dev]'
make test
make lint
make coverage
python -m build
```

Tests run without model credentials. Browser smoke tests additionally require the `capture`
extra and installed Chromium. See [Contributing](CONTRIBUTING.md).

Repository CI checks Python 3.11–3.13, package builds, and the documented suite outcomes. A separate
Chromium job checks actual capture and report interactions, then saves the browser example report.

## Current boundaries

- This is an alpha tool. Version 0.2 adds capture and CI workflows, but does not manage baseline
  approval, authentication flows, browser interactions, or screenshot storage.
- Pixel thresholds do not establish intent, accessibility, or functional correctness. Small changes
  can matter; large changes can be intentional. Diff regions are approximate connected components.
- Model confidence is provider-reported, not a calibrated probability. Evaluate semantic gates on
  your own cases before they control a release.
- Capture uses Chromium. Cross-browser orchestration, DOM/accessibility-tree evidence, rootless
  baseline/candidate container orchestration, and PR annotations remain future work.
- Reports embed source screenshots and include paths and metadata. Review their contents before
  sharing them. Ignore regions do not redact report screenshots.

Created by [Zhexun Hu](https://github.com/RealJasonHu). Licensed under the [MIT License](LICENSE).
