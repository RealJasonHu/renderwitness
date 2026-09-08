# CI integration

[README](../README.md) · [Suite configuration](workflows.md#author-a-suite)

RenderWitness gates are opt-in. A completed comparison can have provider verdict `review` or
`fail` while the CI gate passes, if no configured rule is violated. This lets teams begin by
collecting evidence and introduce release rules after evaluating their own cases.

## Gate rules

| Policy field | Default | Failure condition |
|---|---|---|
| `max_change_ratio` | `null` | Measured nonignored change ratio is strictly greater than the budget |
| `fail_on_severity` | `null` | Any finding meets/exceeds the chosen severity and `min_confidence` |
| `min_confidence` | `0.8` | Applies to the severity rule only; it is not a separate failure rule |
| `fail_on_review` | `false` | Provider verdict is either `review` or `fail` |

Ratios and confidence values are in [0, 1]. A 1% budget is `0.01`, not `1`.
Equality with the change budget passes; equality with the severity confidence threshold qualifies
for failure. Severity order is `ignore < minor < major < critical`.
Enabled rules combine with OR: any violation fails the gate.

`fail_on_review` is not filtered by confidence. An empty policy passes completed comparisons,
but never converts operational errors into passes. A provider's confidence is self-reported;
RenderWitness does not calibrate it.

For a deterministic pixel budget:

```bash
renderwitness compare baseline.png candidate.png \
  --max-change-ratio 0.01 \
  --output reports/change
```

For an explicitly configured semantic rule:

```bash
renderwitness compare baseline.png candidate.png \
  --provider openai-compatible \
  --fail-on-severity major \
  --min-confidence 0.85 \
  --output reports/change
```

Configure the provider environment as shown in the [model guide](model-guide.md).
With the `demo` provider, severity is a synthetic pixel heuristic; a semantic gate against that
provider does not test real defect detection.

The legacy `--fail-on-change` flag remains supported and sets an effective zero changed-pixel
budget. It takes precedence if also supplied with `--max-change-ratio`.
Suite policies use the JSON fields above; provider options are set on the suite command.

## Status and exit codes

| Result | Case status | Process exit |
|---|---|---|
| Completed, all configured rules pass | `passed` | `0` |
| Completed, at least one rule fails | `failed` | `1` |
| Input, model, configuration, capture, or report error | `error` where a case exists | `2` |

For suites, any error takes precedence over any gate failure. Cases run sequentially and continue
after individual failures or errors. Invalid global configuration fails before execution.

A model error after successful diffing attempts a fallback evidence report, clearly labeled
`unavailable`. It remains an operational error with exit 2. If an image could not be loaded or
the output could not be written, a report may not exist.

## GitHub Actions example

The following workflow assumes your tests already produce the image pairs referenced by a checked-in
`tests/visual/suite.json`. Replace that path with your own configuration. The suite output must
be a new or empty directory; the run ID and attempt distinguish repeated executions.

```yaml
name: Visual regression

on:
  pull_request:

permissions:
  contents: read

jobs:
  visual:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
      - run: python -m pip install -e .

      # Add your application's screenshot-generation step here.
      - name: Compare screenshots
        run: >-
          renderwitness suite tests/visual/suite.json
          --provider demo
          --output reports/visual-${{ github.run_id }}-${{ github.run_attempt }}

      - name: Keep visual evidence
        if: always()
        uses: actions/upload-artifact@v6
        with:
          name: visual-evidence
          path: reports/visual-${{ github.run_id }}-${{ github.run_attempt }}
          if-no-files-found: warn

      - name: Add job summary
        if: always()
        run: |
          report="reports/visual-${{ github.run_id }}-${{ github.run_attempt }}/summary.md"
          if [ -f "$report" ]; then
            cat "$report" >> "$GITHUB_STEP_SUMMARY"
          fi
```

The Markdown file links to local case reports. Those relative links work when the output directory
is preserved, but do not become hosted evidence links in the Actions job summary. Download the
artifact and open its `index.html` for full navigation.

If you capture with RenderWitness in Linux CI, install the browser extra and browser dependencies
before the screenshot step:

```bash
python -m pip install -e '.[capture]'
python -m playwright install --with-deps chromium
```

Do not suppress the comparison's exit code merely to upload artifacts; use an unconditional artifact
step so a failing check stays failed. Hosted model runs require your own secret configuration and
data-sharing decision. The repository's default tests do not require those secrets.

## Artifact contract

| File | Purpose |
|---|---|
| `index.html` | Suite overview with links to available case reports |
| `summary.json` | Structured cases, counts, effective gates, errors, and exit code |
| `summary.md` | Compact review table for local use or a CI summary |
| `junit.xml` | One testcase per scenario; gate violations are failures, operational problems are errors |
| `cases/<id>/index.html` | Self-contained review viewer for a completed or fallback case |
| `cases/<id>/report.json` | Validated analysis or unavailable-provider fallback |
| `cases/<id>/comparison.json` | Deterministic measurements retained before provider analysis |
| `cases/<id>/images/` | Copies of the compared source images |

Case files appear only after the relevant stage succeeds. Capture sidecars remain beside the
original captured PNGs and are not automatically copied into suite artifacts. Retain them
separately if browser provenance matters to your workflow.

## Introducing a gate

Start with a representative suite and no blocking rules. Fix unstable capture conditions, inspect
expected and unexpected changes, then select a pixel budget per scenario. If adding a real model,
measure false positives, missed defects, structured-output failures, and repeatability on labeled
cases before relying on severity rules.

Baseline updates remain an explicit repository/workflow decision. RenderWitness does not approve
new baselines or interpret a passing gate as authorization to deploy.
