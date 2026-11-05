#!/bin/sh
# The hosted setup (#1265): the tools a job needs on GitHub's ubuntu-24.04
# image, where the PC's image has them built in.
#
#   setup.sh python|chromium|zsh...
#
#   python    python-build-standalone's CPython at the PC's pin (pins.sh),
#             SHA-256 checked, first on the PATH of the job's later steps
#   chromium  the image's Google Chrome if it is the PC's pinned version
#             (ubuntu-24.04's is, at image 20261026), else Chrome for Testing
#             at that pin, SHA-256 checked; as `chromium` (the first name the
#             jobs look for), first on PATH
#   zsh       from the image's apt, if it is missing (as the PC's image has it)
#
# Only on GitHub's own runners (RUNNER_ENVIRONMENT=github-hosted) or Jog,
# whose image has no Chromium (service.sh, #2467), and x86-64 only: anywhere
# else it changes nothing and exits 2, so the PC's path never runs it.
# Everything it downloads goes in $RUNNER_TEMP, emptied after each job (a
# Jog machine is discarded with it). Exits 1 on a failed download, checksum
# or version.
set -eu
HERE="$(dirname "$0")"
usage() { echo "setup.sh: usage: setup.sh python|chromium|zsh..." >&2; exit 2; }
refuse() { echo "setup.sh: $*: nothing set up" >&2; exit 2; }
fail() { echo "setup.sh: $*" >&2; exit 1; }

[ "$#" -ge 1 ] || usage
for tool; do case "$tool" in python | chromium | zsh) ;; *) usage ;; esac; done
# shellcheck source=service.sh
. "$HERE/service.sh"
[ "$(runner_service)" != none ] || refuse "not one of GitHub's own runners or Jog (RUNNER_ENVIRONMENT=${RUNNER_ENVIRONMENT:-unset})"
[ "$(uname -m)" = x86_64 ] || refuse "no pinned build for $(uname -m)"
temp="${RUNNER_TEMP:?}" path="${GITHUB_PATH:?}"
# shellcheck source=pins.sh
. "$HERE/pins.sh"

# fetch URL SHA256 FILE: download URL to FILE and check it, or fail.
fetch() {
  curl -fsSL --retry 5 --retry-delay 10 -o "$3" "$1" || fail "could not download $1"
  echo "$2  $3" | sha256sum -c - > /dev/null 2>&1 || fail "$1 is not the pinned build (SHA-256)"
}

setup_python() {
  file="$temp/python.tar.gz" dir="$temp/hosted-python"
  fetch "https://github.com/astral-sh/python-build-standalone/releases/download/$PYTHON_BUILD/cpython-$PYTHON_VERSION+$PYTHON_BUILD-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz" "$PYTHON_SHA256" "$file"
  rm -rf "$dir" && mkdir -p "$dir"
  tar -xzf "$file" -C "$dir" --strip-components=1 || fail "could not unpack $file"
  rm -f "$file"
  said="$("$dir/bin/python3" --version 2>&1)" || fail "python3 did not run: $said"
  [ "$said" = "Python $PYTHON_VERSION" ] || fail "python3 says '$said', not Python $PYTHON_VERSION"
  echo "$dir/bin" >> "$path"
  echo "setup.sh: $said, first on PATH"
}

setup_chromium() {
  file="$temp/chrome.zip" dir="$temp/hosted-chrome"
  # The image's own Chrome, when it is the pinned version: nothing downloaded.
  image="$(command -v google-chrome || true)"
  if [ -n "$image" ] && said="$("$image" --version 2>&1)" && case "$said " in *" $CHROME_VERSION "*) true ;; *) false ;; esac; then
    rm -rf "$dir" && mkdir -p "$dir/bin"
    ln -s "$image" "$dir/bin/chromium"
    echo "$dir/bin" >> "$path"
    echo "setup.sh: the image's $said, as chromium, first on PATH"
    return 0
  fi
  fetch "https://storage.googleapis.com/chrome-for-testing-public/$CHROME_VERSION/linux64/chrome-linux64.zip" "$CHROME_SHA256" "$file"
  rm -rf "$dir" && mkdir -p "$dir/bin"
  unzip -q "$file" -d "$dir" || fail "could not unpack $file"
  rm -f "$file"
  ln -s "$dir/chrome-linux64/chrome" "$dir/bin/chromium"
  said="$("$dir/bin/chromium" --version 2>&1)" || fail "chromium did not run: $said"
  case "$said" in *" $CHROME_VERSION"*) ;; *) fail "chromium says '$said', not $CHROME_VERSION" ;; esac
  echo "$dir/bin" >> "$path"
  echo "setup.sh: $said, as chromium, first on PATH"
}

setup_zsh() {
  if command -v zsh > /dev/null; then echo "setup.sh: zsh is already on the image"; return 0; fi
  # Ubuntu 24.04's existing deb822 sources, including the image's mirrors and
  # Signed-By, unchanged. Never invent a fallback for an unsupported layout or
  # edit the image's global sources to work around an unrelated repository.
  sources="$temp/zsh.sources"
  cat /etc/apt/sources.list.d/ubuntu.sources > "$sources" || fail "could not read Ubuntu apt sources"
  [ -s "$sources" ] || fail "Ubuntu apt sources are empty"
  # Apply the same source boundary to installation; unrelated cached package
  # indexes must not become candidates either. APT still validates the source
  # syntax/signatures, and every required refresh error (even transient) fails.
  set -- -o "Dir::Etc::sourcelist=$sources" -o Dir::Etc::sourceparts=-
  sudo -n apt-get "$@" update -q --error-on=any > /dev/null || fail "apt-get update failed"
  sudo -n apt-get "$@" install -y zsh > /dev/null || fail "apt-get install zsh failed"
  command -v zsh > /dev/null || fail "zsh is still missing"
  echo "setup.sh: zsh from the image's apt"
}

for tool; do "setup_$tool"; done
