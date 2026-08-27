# Benchmarks

`demo.json` is the machine-readable ground truth for the bundled screenshot pair. It separates one
cosmetic shadow adjustment from two user-facing failures and includes expected regions for IoU-based
localization checks.

Version 0.1 uses this case in the offline integration suite. A future benchmark runner will compare
pixel thresholding, full-frame VLM review, and RenderWitness's region-grounded pipeline across a
larger mutation corpus.

All contributed benchmark images must be synthetic, permissively licensed, or owned by the
contributor. Do not add customer or private-product screenshots.
