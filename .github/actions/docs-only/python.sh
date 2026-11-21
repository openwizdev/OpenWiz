#!/bin/sh
set -eu
case "$(uname -m)" in
  x86_64) sum=df15fe60d3ff55bf9dcf25824b5572756bb8816ff93865a273d3301d7066a8b7 ;;
  aarch64) sum=578d9da1983463ffb0c8c98ab0da2f18177f44069328eb0af847860c1eb05c3e ;;
  *) echo "no pinned Python for $(uname -m)" >&2; exit 1 ;;
esac
curl -fsSL --retry 5 --retry-delay 10 -o "$RUNNER_TEMP/python.tar.gz" \
  "https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.13.18+20261026-$(uname -m)-unknown-linux-gnu-install_only_stripped.tar.gz"
echo "$sum  $RUNNER_TEMP/python.tar.gz" | sha256sum -c -
python="$(mktemp -d "$RUNNER_TEMP/python.XXXXXX")"
tar -xzf "$RUNNER_TEMP/python.tar.gz" -C "$python" --strip-components=1
export PATH="$python/bin:$PATH"
echo "$python/bin" >> "$GITHUB_PATH"
python3 --version
