# A local page with inspectable visual regressions

This is a fictional bilingual analytics dashboard, designed to make browser
capture and visual comparison reproducible without a server or network access.
Open `baseline.html` and `candidate.html` directly, or capture their absolute
`file://` URLs. The pages share all markup and data; the candidate adds one body
class that activates three clearly marked regression rules in `dashboard.css`.

| Seeded change | Desktop | Mobile | Why it matters |
| --- | --- | --- | --- |
| Export button forced to 88px | Visible | Visible | The report-export label is clipped, including its Chinese translation |
| Notification SVG hidden | Visible | Visible | The notification button loses its identifying icon |
| Three fixed-width metric columns | Inactive | Visible | Cards overflow a narrow viewport instead of stacking, hiding metrics |

Recommended viewports are `1280 × 800` and `390 × 844`. Capture both pages with
the same viewport, `full_page=False`, and `mask_selectors=("#live-clock",)`.
The UTC clock is intentionally dynamic; the rest of the fixture has fixed data
and no remote fonts, images, libraries or API calls. It exercises Latin and
Chinese text using locally available system fonts, so use the same OS and font
environment for pixel-identical runs.

```python
from pathlib import Path
from renderwitness.capture import CaptureOptions, capture_page

root = Path("examples/web").resolve()
options = CaptureOptions(width=390, height=844, mask_selectors=("#live-clock",))
for name in ("baseline", "candidate"):
    capture_page(
        (root / f"{name}.html").as_uri(),
        f"artifacts/mobile-{name}.png",
        options=options,
    )
```

Then use the ordinary image-comparison workflow on the two generated PNGs.
The offline demo provider identifies pixel changes and suggests review; it does
not prove the three semantic diagnoses in this table. A configured VLM provider
can attempt semantic review, which still needs human assessment.

Buttons and navigation illustrate layout only; they do not export reports or
contact a backend. See [capture documentation](../../docs/capture.md) for browser
installation, metadata, masking behavior and the real browser test command.
