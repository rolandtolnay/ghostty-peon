#!/usr/bin/env sh
set -eu

python3 -m unittest discover -s tests
python3 -m py_compile hooks/*.py
npx --yes esbuild pi-extension/index.ts \
  --bundle \
  --platform=node \
  --format=esm \
  --external:@earendil-works/pi-coding-agent \
  --outfile=/tmp/ghostty-peon-extension-check.mjs
