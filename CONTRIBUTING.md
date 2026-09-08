# Contributing to RenderWitness

Contributions should make screenshot review easier to reproduce, inspect, or integrate.
Bug reports, focused fixes, documentation corrections, and synthetic regression cases are welcome.

## Set up development

Use Python 3.11 or later:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
make test
make lint
```

For browser capture work:

```bash
python -m pip install -e '.[dev,capture]'
python -m playwright install chromium
```

The core tests must stay runnable without a network, GPU, model download, or API credentials.
Browser-dependent validation belongs in a clearly identified optional smoke workflow.

## Find the relevant module

| Change | Starting point |
|---|---|
| Pixel comparison and ignore rectangles | `src/renderwitness/diff.py`, `models.py` |
| Provider parsing and prompts | `src/renderwitness/providers.py`, `analyzer.py` |
| Browser capture | `src/renderwitness/capture.py` |
| CI decisions and scenario configuration | `src/renderwitness/policy.py`, `suite.py` |
| Case and suite viewers | `src/renderwitness/report.py`, `suite_report.py` |
| CLI options | `src/renderwitness/cli.py` |

Read the [architecture guide](docs/architecture.md) for the contracts between these modules.

## Validate a change

For behavioral changes, add a focused regression test that would fail without the change.
Use small generated images and fake HTTP responses when possible. Validate important edge cases:
empty/mismatched inputs, exact thresholds, excluded pixels, malformed model output, and output errors.

```bash
make test
make lint
make coverage
python -m build
renderwitness demo --output reports/review-demo
renderwitness suite examples/suite.json --output reports/review-suite
```

Choose a new or empty suite directory on subsequent runs. The bundled suite intentionally returns
exit 1: its seeded regression should fail, while the unchanged control and review-only case pass.
Open the generated HTML when changing the viewer. Inspect narrow and wide layouts, image alignment,
filters, and empty/error states.
JSON or DOM assertions alone do not establish visual quality.

For capture changes, also run the [browser fixture](examples/README.md):

```bash
python scripts/run_browser_demo.py --output reports/browser-review
RENDERWITNESS_BROWSER_TESTS=1 pytest tests/test_capture.py tests/test_report_browser.py
```

The browser demo script returns 0 when both expected regression failures and the passing control
are verified. Confirm that a missing readiness/mask selector and an invalid URL produce clear errors.

Regenerate the bundled synthetic screenshots only when intentionally changing their renderer:

```bash
python scripts/generate_demo_assets.py
```

Review the resulting image and benchmark metadata changes together.

## Pull requests

Describe the problem, resulting behavior, and relevant validation. Include a minimal reproducer
for bug fixes. Keep unrelated formatting and generated artifacts out of the change.

- Preserve the distinction between measured pixels, provider interpretations, and CI decisions.
- Keep the `demo` provider deterministic and explicitly synthetic.
- Document changed thresholds, prompts, output contracts, and configuration defaults.
- Update both README languages when changing user-facing quick-start behavior.
- Include source and license information for new fixtures; use synthetic or permissively licensed data.
- Never commit customer screenshots, credentials, or reports containing private application data.
- Do not claim model accuracy from a schema test, mock response, or offline demo.
- Do not silently turn operational errors into passing CI gates.

For vulnerabilities, follow [SECURITY.md](SECURITY.md). Contributions are licensed under the
repository's [MIT License](LICENSE).
