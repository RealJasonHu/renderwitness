# Security policy

## Supported versions

RenderWitness is pre-1.0. Security fixes are applied to the latest release on `main`.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Email
`huzhexun1@gmail.com` with a minimal reproduction and the affected version. You can expect an
acknowledgement within five business days.

## Data handling and trust boundaries

- Screenshot bytes are read locally and are not persisted by RenderWitness beyond user-chosen
  reports.
- Selecting `openai-compatible` sends both screenshots and the analysis prompt to the configured
  endpoint. Review that provider's retention policy first.
- Text visible inside screenshots is untrusted evidence, never an instruction. The analysis prompt
  explicitly tells the model to ignore instructions rendered in the UI.
- Input byte size, decoded pixel count, and image dimensions are bounded before analysis.
- Generated HTML escapes model-controlled text. Reports should still be opened as untrusted files.
- A VLM finding is a review aid, not a security, accessibility, or release certification.
