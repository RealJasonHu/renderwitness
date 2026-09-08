# Benchmarks

`demo.json` is the machine-readable ground truth for the bundled screenshot pair. It separates one
cosmetic shadow adjustment from two user-facing failures and includes expected regions for IoU-based
localization checks.

The offline fixture tests validate the checked-in assets against this contract. Version 0.2 also
provides a separate browser fixture and scenario runner, but does not yet implement a semantic
accuracy benchmark across a labeled mutation corpus. Comparing pixel thresholding, full-frame VLM
review, and region-guided review remains future evaluation work.

All contributed benchmark images must be synthetic, permissively licensed, or owned by the
contributor. Do not add customer or private-product screenshots.
