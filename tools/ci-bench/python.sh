#!/bin/sh
# Same pinned runtime as CI's installer proofs; the PC image may omit Python.
set -eu
if command -v python3 >/dev/null; then
  python3 --version
  exit 0
fi
: "${RUNNER_TEMP:?runtime bootstrap is for Actions}"
: "${GITHUB_PATH:?runtime bootstrap needs the next-step PATH file}"
case "$(uname -m)" in
  x86_64) sum=df15fe60d3ff55bf9dcf25824b5572756bb8816ff93865a273d3301d7066a8b7 ;;
  aarch64) sum=578d9da1983463ffb0c8c98ab0da2f18177f44069328eb0af847860c1eb05c3e ;;
  *) echo 'No pinned Python for this architecture' >&2; exit 1 ;;
esac
archive="$(mktemp "$RUNNER_TEMP/ci-bench-python.XXXXXX")"
trap 'rm -f "$archive"' EXIT HUP INT TERM
curl -fsSL --retry 3 -o "$archive" \
  "https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.13.18+20261026-$(uname -m)-unknown-linux-gnu-install_only_stripped.tar.gz"
printf '%s  %s\n' "$sum" "$archive" | sha256sum -c -
python_dir="$(mktemp -d "$RUNNER_TEMP/ci-bench-python.XXXXXX")"
tar -xzf "$archive" -C "$python_dir" --strip-components=1
printf '%s\n' "$python_dir/bin" >> "$GITHUB_PATH"
"$python_dir/bin/python3" --version
