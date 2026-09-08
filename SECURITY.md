# Security policy

## Supported versions

RenderWitness is pre-1.0. Security fixes target the latest code on `main`; older alpha versions
do not have a separate maintenance commitment. Include the installed version and, for a source
checkout, the commit identifier in a report.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Email
`huzhexun1@gmail.com` with a minimal reproduction and the affected version. You can expect an
acknowledgement within five business days.

## Data handling and trust boundaries

- The offline `demo` provider makes no network or model calls. It reads local image metrics.
- Browser capture loads the requested page and its resources in a fresh, unauthenticated Chromium
  context. It does not reuse a personal browser profile, cookies, or login session. The page's
  JavaScript still runs. Network access is part of capture when using a network URL.
- Capture writes a PNG and metadata sidecar to the requested location. URLs in the sidecar omit
  credentials, query strings, and fragments. URL paths, selectors, filenames, and page pixels remain.
  Capture error messages omit the browser's raw exception text.
- Selecting `openai-compatible` sends normalized screenshot copies, diff metadata, and the prompt
  to the configured endpoint. The built-in adapter covers ignored rectangles in those copies;
  a custom provider controls its own handling. The endpoint's data retention policy still applies.
- Reports embed source screenshot content and include file paths and hashes. Suites also copy
  source images into their output directory. Ignore rectangles do not redact report screenshots.
  Capture masks change the captured PNG; inspect the saved result before sharing sensitive pages.
- API keys are read from the environment and used for provider authentication, not stored in report
  records. Provider errors can include a shortened server-response message; inspect CI logs before
  publishing them.
- Input byte size, decoded pixel count, region counts, and schema fields are bounded. Images must
  have matching dimensions. These controls are resource limits, not a complete sandbox for image
  decoders, browsers, or model endpoints.
- Model-authored text is escaped in HTML reports, and model output is schema-validated. The prompt
  treats screenshot text as untrusted content. These measures do not prove a model interpretation
  correct or establish immunity to visual prompt injection.
- A VLM finding is a review aid, not a security, accessibility, or release certification. Operational
  errors return an error status even when a fallback evidence report is available.

See [architecture](docs/architecture.md), [capture](docs/capture.md), and the
[model guide](docs/model-guide.md) for the corresponding data and failure contracts.
