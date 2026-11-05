#!/bin/sh
# The hosted runner kit's checks (#1265). Run from anywhere:
#   sh ci/hosted/test.sh
# 1. guard.sh, the runner guard, on synthetic GitHub variables: a pull request
#    from a fork never runs on a runner that is not GitHub's own, and only a
#    push or the nightly run on main, on GitHub's runner or Jog (#2467), may
#    save GitHub's cache; Jog is still not GitHub's own for a fork.
# 2. setup.sh on a fake ubuntu-24.04 image: fake curl, sudo, apt-get and
#    uname, synthetic archives at synthetic pins (pins.sh beside a copy).
# 3. cache.sh (ci/runner) stays out of the way on GitHub's runners.
# 4. ci.yml, statically: each job's runner choice sends a fork's pull request
#    to ubuntu-24.04, the guard runs before anything the pull request ships,
#    and GitHub's cache steps run only on GitHub's runners, saving only when
#    the guard says so. Pinned by SHA.
# Needs sh, tar, gzip, unzip, sha256sum and python3 (for the zip: the PC's
# runner image has no zip program). Reads nothing outside this
# repository but /tmp.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CI="$ROOT/.github/workflows/ci.yml"
fails=0
ok() { echo "ok   $*"; }
bad() { echo "FAIL $*"; fails=$((fails + 1)); }
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

# --- 1. guard.sh -------------------------------------------------------------
# guard NAME WANT_STATUS WANT_OUTPUT VAR=VALUE...: run guard.sh with only these
# GitHub variables (and GITHUB_OUTPUT); WANT_OUTPUT is GITHUB_OUTPUT's lines,
# joined by spaces, or `-` for none.
guard() {
  name="$1" want_status="$2" want_out="$3"
  shift 3
  : > "$T/out"
  env -i PATH="$PATH" GITHUB_OUTPUT="$T/out" "$@" sh "$HERE/guard.sh" > "$T/said" 2>&1
  status=$?
  got="$(tr '\n' ' ' < "$T/out" | sed 's/ $//')"
  [ -n "$got" ] || got=-
  if [ "$status" = "$want_status" ] && [ "$got" = "$want_out" ]; then ok "guard: $name"; else bad "guard: $name (exit $status, output [$got], said: $(tr '\n' ' ' < "$T/said"))"; fi
}
R=GITHUB_REPOSITORY=owner/repo
PR="GITHUB_EVENT_NAME=pull_request GITHUB_REF=refs/pull/7/merge"
# shellcheck disable=SC2086 # $PR is two words on purpose
{
guard "a pull request from this repository, on the PC" 0 "hosted=false save=false service=none" $R $PR HEAD_REPO=owner/repo RUNNER_ENVIRONMENT=self-hosted
guard "a pull request from this repository, on GitHub's runner" 0 "hosted=true save=false service=github" $R $PR HEAD_REPO=owner/repo RUNNER_ENVIRONMENT=github-hosted
guard "a fork's pull request on a self-hosted runner (closedwiz-pc) fails" 1 - $R $PR HEAD_REPO=someone/repo RUNNER_ENVIRONMENT=self-hosted
guard "a fork's pull request on GitHub's runner" 0 "hosted=true save=false service=github" $R $PR HEAD_REPO=someone/repo RUNNER_ENVIRONMENT=github-hosted
guard "a pull request whose head is unknown (a deleted fork), self-hosted, fails" 1 - $R $PR RUNNER_ENVIRONMENT=self-hosted
guard "a fork's pull request where the runner's kind is unknown fails" 1 - $R $PR HEAD_REPO=someone/repo
guard "pull_request_target from a fork, self-hosted, fails" 1 - $R GITHUB_EVENT_NAME=pull_request_target GITHUB_REF=refs/heads/main HEAD_REPO=someone/repo RUNNER_ENVIRONMENT=self-hosted
guard "an event that names no head (issue_comment), self-hosted, fails" 1 - $R GITHUB_EVENT_NAME=issue_comment GITHUB_REF=refs/heads/main RUNNER_ENVIRONMENT=self-hosted
guard "a push to main on GitHub's runner saves" 0 "hosted=true save=true service=github" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main RUNNER_ENVIRONMENT=github-hosted
guard "the nightly run on main on GitHub's runner saves" 0 "hosted=true save=true service=github" $R GITHUB_EVENT_NAME=schedule GITHUB_REF=refs/heads/main RUNNER_ENVIRONMENT=github-hosted
guard "a push to main on the PC: its own store, not GitHub's" 0 "hosted=false save=false service=none" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main RUNNER_ENVIRONMENT=self-hosted
guard "a push to another branch never saves" 0 "hosted=true save=false service=github" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/room/x RUNNER_ENVIRONMENT=github-hosted
guard "a push of a tag named main never saves" 0 "hosted=true save=false service=github" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/tags/main RUNNER_ENVIRONMENT=github-hosted
guard "a manual run on main never saves" 0 "hosted=true save=false service=github" $R GITHUB_EVENT_NAME=workflow_dispatch GITHUB_REF=refs/heads/main RUNNER_ENVIRONMENT=github-hosted
guard "a merge group never saves" 0 "hosted=true save=false service=github" $R GITHUB_EVENT_NAME=merge_group GITHUB_REF=refs/heads/gh-readonly-queue/main/pr-7 RUNNER_ENVIRONMENT=github-hosted
guard "a merge group on the PC" 0 "hosted=false save=false service=none" $R GITHUB_EVENT_NAME=merge_group GITHUB_REF=refs/heads/gh-readonly-queue/main/pr-7 RUNNER_ENVIRONMENT=self-hosted
J="RUNNER_ENVIRONMENT=self-hosted RUNNER_NAME=jog-0123abcd-0123456789ab JOG_RUNNER_SCOPE=1:1"
guard "a pull request from this repository, on Jog: GitHub's cache, restore only" 0 "hosted=false save=false service=jog" $R $PR HEAD_REPO=owner/repo $J
guard "a fork's pull request on Jog still fails" 1 - $R $PR HEAD_REPO=someone/repo $J
guard "a push to main on Jog saves" 0 "hosted=false save=true service=jog" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main $J
guard "the nightly run on main on Jog saves" 0 "hosted=false save=true service=jog" $R GITHUB_EVENT_NAME=schedule GITHUB_REF=refs/heads/main $J
guard "a merge group on Jog never saves" 0 "hosted=false save=false service=jog" $R GITHUB_EVENT_NAME=merge_group GITHUB_REF=refs/heads/gh-readonly-queue/main/pr-7 $J
guard "a push to another branch on Jog never saves" 0 "hosted=false save=false service=jog" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/room/x $J
guard "a manual run on main on Jog never saves" 0 "hosted=false save=false service=jog" $R GITHUB_EVENT_NAME=workflow_dispatch GITHUB_REF=refs/heads/main $J
guard "a Jog-named runner without Jog's scope is not Jog" 0 "hosted=false save=false service=none" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main RUNNER_ENVIRONMENT=self-hosted RUNNER_NAME=jog-0123abcd-0123456789ab
guard "Jog's scope on another runner's name (the PC) is not Jog" 0 "hosted=false save=false service=none" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main RUNNER_ENVIRONMENT=self-hosted RUNNER_NAME=closedwiz-pc JOG_RUNNER_SCOPE=1:1
guard "a name that only starts like Jog's is not Jog" 0 "hosted=false save=false service=none" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main RUNNER_ENVIRONMENT=self-hosted RUNNER_NAME=jog-0123abcd-0123456789ab-x JOG_RUNNER_SCOPE=1:1
guard "Jog's variables on a runner of unknown kind are not Jog" 0 "hosted=false save=false service=none" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main RUNNER_NAME=jog-0123abcd-0123456789ab JOG_RUNNER_SCOPE=1:1
# R1 on #2473: a runner name is one whole line. A newline before, inside or
# after Jog's name, or a carriage return, is not Jog (grep -x matches lines).
NL='
'
CR="$(printf '\r')"
jog_break() {
  guard "a Jog name with $1 is not Jog" 0 "hosted=false save=false service=none" $R GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main RUNNER_ENVIRONMENT=self-hosted "RUNNER_NAME=$2" JOG_RUNNER_SCOPE=1:1
}
jog_break "a line before it" "impostor${NL}jog-0123abcd-0123456789ab"
jog_break "a line after it" "jog-0123abcd-0123456789ab${NL}impostor"
jog_break "a newline inside it" "jog-0123abcd-${NL}0123456789ab"
jog_break "a trailing newline" "jog-0123abcd-0123456789ab${NL}"
jog_break "a trailing carriage return" "jog-0123abcd-0123456789ab${CR}"
guard "no repository: refused" 2 - $PR HEAD_REPO=owner/repo RUNNER_ENVIRONMENT=github-hosted
}
env -i PATH="$PATH" GITHUB_REPOSITORY=owner/repo GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main RUNNER_ENVIRONMENT=github-hosted sh "$HERE/guard.sh" > /dev/null 2>&1
if [ $? = 2 ]; then ok "guard: no GITHUB_OUTPUT: refused"; else bad "guard: no GITHUB_OUTPUT was not refused"; fi

# --- 2. setup.sh on a fake image ---------------------------------------------
# The image: real tools only from this list, so zsh, python3 and chromium are
# missing until setup.sh brings them. Fake curl serves the synthetic archives
# and logs each URL; fake sudo runs its command; fake apt-get logs and, on
# install, adds zsh; fake uname answers $FAKE_ARCH.
IMG="$T/image"
mkdir -p "$IMG/bin" "$IMG/serve/payload/python/bin" "$IMG/serve/payload/chrome-linux64"
for tool in sh cat chmod cp dirname env grep head ln ls mkdir mktemp mv printf readlink rm sed sha256sum tar gzip tr unzip; do
  real="$(command -v "$tool")" || { bad "setup: the test needs $tool"; continue; }
  ln -s "$real" "$IMG/bin/$tool"
done
cat > "$IMG/bin/curl" <<'EOF'
#!/bin/sh
out= url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    --retry | --retry-delay) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
echo "$url" >> "$FAKE_LOG/urls"
case "$url" in
  *cpython-*) cp "$FAKE_SERVE/python.tar.gz" "$out" ;;
  *chrome-linux64.zip) cp "$FAKE_SERVE/chrome.zip" "$out" ;;
  *) echo "fake curl: no such file: $url" >&2; exit 22 ;;
esac
EOF
cat > "$IMG/bin/sudo" <<'EOF'
#!/bin/sh
[ "$1" = -n ] && shift
exec "$@"
EOF
cat > "$IMG/bin/apt-get" <<'EOF'
#!/bin/sh
echo "apt-get $*" >> "$FAKE_LOG/apt"
sources=/etc/apt/sources.list parts=default action= strict= package=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o)
      case "$2" in
        Dir::Etc::sourcelist=*) sources=${2#*=} ;;
        Dir::Etc::sourceparts=*) parts=${2#*=} ;;
        *) echo "fake apt: unexpected configuration $2" >&2; exit 99 ;;
      esac
      shift 2 ;;
    update | install) action=$1; shift ;;
    --error-on=any) strict=1; shift ;;
    -q | -y) shift ;;
    zsh) package=zsh; shift ;;
    *) echo "fake apt: unexpected argument $1" >&2; exit 99 ;;
  esac
done
# Synthetic APT model: effective source selection controls repository reads.
# Missing sources warn (APT may otherwise reuse old indexes); malformed ones
# fail. Authentication is never bypassed. No real apt or network is reachable.
selected=ubuntu
if [ "$sources" != /etc/apt/sources.list ]; then
  content=$(cat "$sources") || content=
  if [ -z "$content" ]; then
    selected=none
  elif ! printf '%s\n' "$content" | grep -qx 'Types: deb'; then
    echo 'E: Malformed entry in sources file' >&2; exit 100
  else
    selected=ubuntu
  fi
fi
[ "$parts" = - ] || selected="$selected third-party"
case "$action" in
  update | install) printf '%s\n' "${content:-}" > "$FAKE_LOG/$action.sources" ;;
esac
echo "$action $selected" >> "$FAKE_LOG/apt-effects"
case "$action" in
  update)
    case "$selected:${FAKE_APT_FAILURE:-}" in
      *third-party*:unrelated) echo 'E: unrelated repository has no Release file' >&2; exit 100 ;;
      *ubuntu*:update) echo 'E: required Ubuntu update failed' >&2; exit 100 ;;
      *ubuntu*:signature) echo 'E: Ubuntu signature could not be verified' >&2; exit 100 ;;
      *ubuntu*:transient)
        echo 'W: required Ubuntu index could not be fetched' >&2
        [ -z "$strict" ] && exit 0
        exit 100 ;;
    esac
    [ "$selected" != ubuntu ] || : > "$FAKE_LOG/refreshed"
    ;;
  install)
    [ "$package" = zsh ] || exit 99
    [ "${FAKE_APT_FAILURE:-}" != install ] || { echo 'E: install failed' >&2; exit 100; }
    [ "${FAKE_APT_FAILURE:-}" != install-signature ] || { echo 'E: package cannot be authenticated' >&2; exit 100; }
    [ "${FAKE_APT_FAILURE:-}" != presence ] || exit 0
    # Broad healthy refresh is retained as the old implementation's control.
    if [ "$selected" = ubuntu ] && [ ! -f "$FAKE_LOG/refreshed" ]; then exit 100; fi
    printf '#!/bin/sh\necho "zsh 5.9 (x86_64-ubuntu-linux-gnu)"\n' > "$FAKE_BIN/zsh"
    chmod +x "$FAKE_BIN/zsh"
    ;;
  *) exit 99 ;;
esac
EOF
# Read the real production source-file boundary without touching /etc. Other
# cat calls still use the real program. Never overwrite its symlink target.
mv "$IMG/bin/cat" "$IMG/bin/real-cat"
cat > "$IMG/bin/cat" <<'EOF'
#!/bin/sh
if [ "$#" = 1 ] && [ "$1" = /etc/apt/sources.list.d/ubuntu.sources ]; then
  echo source-read >> "$FAKE_LOG/source-reads"
  case "${FAKE_SOURCE_MODE:-healthy}" in
    missing | unreadable) echo 'cat: Ubuntu sources unavailable' >&2; exit 1 ;;
    empty) exit 0 ;;
    malformed) echo 'malformed source'; exit 0 ;;
  esac
  exec real-cat "$FAKE_LOG/ubuntu.sources"
fi
exec real-cat "$@"
EOF
chmod +x "$IMG/bin/cat"
cat > "$IMG/bin/uname" <<'EOF'
#!/bin/sh
echo "${FAKE_ARCH:-x86_64}"
EOF
chmod +x "$IMG/bin/curl" "$IMG/bin/sudo" "$IMG/bin/apt-get" "$IMG/bin/uname"
printf '#!/bin/sh\necho "Python 3.99.1"\n' > "$IMG/serve/payload/python/bin/python3"
printf '#!/bin/sh\necho "Google Chrome for Testing 999.0.1.2"\n' > "$IMG/serve/payload/chrome-linux64/chrome"
chmod +x "$IMG/serve/payload/python/bin/python3" "$IMG/serve/payload/chrome-linux64/chrome"
tar -czf "$IMG/serve/python.tar.gz" -C "$IMG/serve/payload" python
python3 -I -c '
import os, sys, zipfile
root, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w") as z:
    for name in ("chrome-linux64/", "chrome-linux64/chrome"):
        info = zipfile.ZipInfo(name)
        info.external_attr = (0o40755 if name.endswith("/") else 0o100755) << 16
        z.writestr(info, b"" if name.endswith("/") else open(os.path.join(root, name), "rb").read())
' "$IMG/serve/payload" "$IMG/serve/chrome.zip" || bad "setup: could not build the synthetic Chrome zip"
# A copy of setup.sh with synthetic pins beside it.
KIT="$T/kit"
mkdir -p "$KIT"
cp "$HERE/setup.sh" "$KIT/setup.sh" 2> /dev/null || bad "setup: ci/hosted/setup.sh is missing"
cp "$HERE/service.sh" "$KIT/service.sh" 2> /dev/null || bad "setup: ci/hosted/service.sh is missing"
cat > "$KIT/pins.sh" <<EOF
PYTHON_VERSION=3.99.1
PYTHON_BUILD=20990101
PYTHON_SHA256=$(sha256sum "$IMG/serve/python.tar.gz" | cut -d' ' -f1)
CHROME_VERSION=999.0.1.2
CHROME_SHA256=$(sha256sum "$IMG/serve/chrome.zip" | cut -d' ' -f1)
EOF
# setup NAME WANT_STATUS ENV... -- ARGS...: one job on a fresh fake image
# (with zsh already on it when has_zsh is set).
has_zsh=
setup() {
  name="$1" want="$2"
  shift 2
  rm -rf "$T/job" && mkdir -p "$T/job/tmp" "$T/job/log" "$T/job/bin"
  : > "$T/job/path"; : > "$T/job/log/urls"; : > "$T/job/log/apt"
  : > "$T/job/log/apt-effects"; : > "$T/job/log/source-reads"
  # synthetic_assumptions: a Noble deb822 source using the image's documented
  # mirror file and existing Ubuntu signing key; no observed machine content.
  cat > "$T/job/log/ubuntu.sources" <<'EOF'
Types: deb
URIs: mirror+file:/etc/apt/apt-mirrors.txt
Suites: noble noble-updates noble-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
  if [ -n "$has_zsh" ]; then printf '#!/bin/sh\necho zsh\n' > "$T/job/bin/zsh"; chmod +x "$T/job/bin/zsh"; fi
  vars=
  while [ "$1" != -- ]; do vars="$vars $1"; shift; done
  shift
  # shellcheck disable=SC2086 # $vars is VAR=VALUE words on purpose
  env -i PATH="$T/job/bin:$IMG/bin" HOME="$T/job" RUNNER_TEMP="$T/job/tmp" GITHUB_PATH="$T/job/path" \
    FAKE_LOG="$T/job/log" FAKE_SERVE="$IMG/serve" FAKE_BIN="$T/job/bin" $vars \
    "$IMG/bin/sh" "$KIT/setup.sh" "$@" > "$T/job/said" 2>&1
  status=$?
  if [ "$status" = "$want" ]; then ok "setup: $name"; else bad "setup: $name (exit $status, want $want: $(tr '\n' ' ' < "$T/job/said"))"; fi
}
# on_path TOOL: TOOL is found on the PATH a later step sees.
on_path() { PATH="$(tr '\n' ':' < "$T/job/path")$T/job/bin:$IMG/bin" "$IMG/bin/sh" -c "command -v $1" > /dev/null 2>&1; }
later() { PATH="$(tr '\n' ':' < "$T/job/path")$T/job/bin:$IMG/bin" "$@" 2>&1; }

setup "Python, Chromium and zsh on GitHub's image" 0 RUNNER_ENVIRONMENT=github-hosted -- python chromium zsh
if [ "$(later python3 --version)" = "Python 3.99.1" ]; then ok "setup: a later step's python3 is the pinned one"; else bad "setup: a later step's python3 says [$(later python3 --version)]"; fi
if [ "$(later chromium --version)" = "Google Chrome for Testing 999.0.1.2" ]; then ok "setup: a later step's chromium is the pinned Chrome for Testing"; else bad "setup: a later step's chromium says [$(later chromium --version)]"; fi
if on_path zsh; then ok "setup: zsh is installed"; else bad "setup: zsh is missing"; fi
if grep -qx 'install ubuntu' "$T/job/log/apt-effects"; then ok "setup: zsh comes from the image's apt"; else bad "setup: apt-get was asked [$(tr '\n' ';' < "$T/job/log/apt")]"; fi
want_urls="https://github.com/astral-sh/python-build-standalone/releases/download/20990101/cpython-3.99.1+20990101-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz;https://storage.googleapis.com/chrome-for-testing-public/999.0.1.2/linux64/chrome-linux64.zip;"
if [ "$(tr '\n' ';' < "$T/job/log/urls")" = "$want_urls" ]; then ok "setup: downloads exactly the pinned builds"; else bad "setup: downloaded [$(tr '\n' ';' < "$T/job/log/urls")]"; fi
case "$(cat "$T/job/path")" in "$T/job/tmp"/*) ok "setup: what it adds to the PATH is in the job's temp folder" ;; *) bad "setup: GITHUB_PATH holds [$(tr '\n' ';' < "$T/job/path")]" ;; esac

# zsh already there: no apt.
has_zsh=1
setup "zsh already installed" 0 RUNNER_ENVIRONMENT=github-hosted FAKE_SOURCE_MODE=missing FAKE_APT_FAILURE=unrelated -- zsh
has_zsh=
if [ ! -s "$T/job/log/apt" ]; then ok "setup: zsh already there: apt is not run"; else bad "setup: zsh already there, apt was run"; fi
if [ ! -s "$T/job/log/source-reads" ]; then ok "setup: installed zsh needs no source discovery"; else bad "setup: installed zsh read apt sources"; fi

# Claim: an unrelated image repository cannot prevent the required zsh setup.
# The old fake always succeeded, hiding the broad refresh's failure before
# install. Exercise the unchanged production script, not an extracted function.
setup "zsh survives an unrelated repository failure" 0 RUNNER_ENVIRONMENT=github-hosted FAKE_APT_FAILURE=unrelated -- zsh
if on_path zsh && [ "$(cat "$T/job/log/apt-effects")" = "$(printf 'update ubuntu\ninstall ubuntu')" ]; then
  ok "setup: only required Ubuntu sources refreshed and installed zsh"
else bad "setup: unrelated repository blocked zsh (effects: $(tr '\n' ';' < "$T/job/log/apt-effects"))"; fi

setup "zsh with healthy Ubuntu sources" 0 RUNNER_ENVIRONMENT=github-hosted -- zsh
if on_path zsh && [ "$(cat "$T/job/log/apt-effects")" = "$(printf 'update ubuntu\ninstall ubuntu')" ]; then
  ok "setup: healthy Ubuntu refresh precedes zsh installation"
else bad "setup: healthy Ubuntu setup did not refresh and install zsh"; fi
if cmp -s "$T/job/log/ubuntu.sources" "$T/job/log/update.sources" && cmp -s "$T/job/log/ubuntu.sources" "$T/job/log/install.sources"; then
  ok "setup: refresh and install retain the existing source, mirror and signing-key bytes"
else bad "setup: Ubuntu source configuration changed at the apt boundary"; fi

# Each true required failure stays fatal, even with old indexes available.
# Assert the diagnostic and stopped boundary, so an unrelated refusal cannot
# stand in for the claimed failure and update failure cannot fall into install.
for failure in update transient signature install install-signature presence; do
  setup "zsh required $failure failure" 1 RUNNER_ENVIRONMENT=github-hosted FAKE_APT_FAILURE="$failure" -- zsh
  case "$failure" in
    update | transient | signature) diagnostic='setup.sh: apt-get update failed'; effects='update ubuntu' ;;
    install | install-signature) diagnostic='setup.sh: apt-get install zsh failed'; effects=$(printf 'update ubuntu\ninstall ubuntu') ;;
    presence) diagnostic='setup.sh: zsh is still missing'; effects=$(printf 'update ubuntu\ninstall ubuntu') ;;
  esac
  if ! on_path zsh && grep -qxF "$diagnostic" "$T/job/said" && [ "$(cat "$T/job/log/apt-effects")" = "$effects" ]; then
    ok "setup: required $failure failure is retained"
  else bad "setup: required $failure failure was masked or failed at the wrong boundary"; fi
done

for source_mode in missing unreadable empty malformed; do
  setup "zsh refuses $source_mode Ubuntu sources" 1 RUNNER_ENVIRONMENT=github-hosted FAKE_SOURCE_MODE="$source_mode" -- zsh
  case "$source_mode" in
    missing | unreadable) diagnostic='setup.sh: could not read Ubuntu apt sources' ;;
    empty) diagnostic='setup.sh: Ubuntu apt sources are empty' ;;
    malformed) diagnostic='setup.sh: apt-get update failed' ;;
  esac
  if ! on_path zsh && grep -qxF "$diagnostic" "$T/job/said" && [ ! -s "$T/job/log/apt-effects" ]; then
    ok "setup: $source_mode sources cannot install from stale indexes or a fallback"
  else bad "setup: $source_mode sources did not fail closed"; fi
done

setup "zsh on arm64 is refused before apt" 2 RUNNER_ENVIRONMENT=github-hosted FAKE_ARCH=aarch64 -- zsh
if [ ! -s "$T/job/log/apt" ] && [ ! -s "$T/job/log/source-reads" ]; then
  ok "setup: unsupported zsh architecture does no apt work"
else bad "setup: unsupported zsh architecture reached apt"; fi

# The image's own Chrome at the pinned version (ubuntu-24.04's, today): used
# as chromium, nothing downloaded. At another version: Chrome for Testing.
image_chrome() {
  printf '#!/bin/sh\necho "Google Chrome %s "\n' "$1" > "$IMG/bin/google-chrome"
  chmod +x "$IMG/bin/google-chrome"
}
image_chrome 999.0.1.2
setup "the image's Chrome at the pin" 0 RUNNER_ENVIRONMENT=github-hosted -- chromium
if [ ! -s "$T/job/log/urls" ] && [ "$(later chromium --version)" = "Google Chrome 999.0.1.2 " ]; then ok "setup: the image's Chrome at the pin is chromium, nothing downloaded"; else bad "setup: with the image's Chrome at the pin: downloaded [$(tr '\n' ';' < "$T/job/log/urls")], chromium says [$(later chromium --version)]"; fi
image_chrome 998.0.0.0
setup "the image's Chrome at another version" 0 RUNNER_ENVIRONMENT=github-hosted -- chromium
if [ "$(later chromium --version)" = "Google Chrome for Testing 999.0.1.2" ]; then ok "setup: the image's Chrome at another version: the pinned Chrome for Testing"; else bad "setup: with the image's Chrome at another version, chromium says [$(later chromium --version)]"; fi
rm -f "$IMG/bin/google-chrome"

# A download that is not the pinned build: refused, nothing on the PATH.
cp "$KIT/pins.sh" "$T/pins.good"
sed -i 's/^PYTHON_SHA256=.*/PYTHON_SHA256=0000000000000000000000000000000000000000000000000000000000000000/' "$KIT/pins.sh"
setup "a Python whose SHA-256 is not the pin fails" 1 RUNNER_ENVIRONMENT=github-hosted -- python
if [ ! -s "$T/job/path" ]; then ok "setup: a bad Python adds nothing to the PATH"; else bad "setup: a bad Python added [$(cat "$T/job/path")]"; fi
cp "$T/pins.good" "$KIT/pins.sh"
sed -i 's/^CHROME_SHA256=.*/CHROME_SHA256=0000000000000000000000000000000000000000000000000000000000000000/' "$KIT/pins.sh"
setup "a Chrome whose SHA-256 is not the pin fails" 1 RUNNER_ENVIRONMENT=github-hosted -- chromium
if [ ! -s "$T/job/path" ]; then ok "setup: a bad Chrome adds nothing to the PATH"; else bad "setup: a bad Chrome added [$(cat "$T/job/path")]"; fi
cp "$T/pins.good" "$KIT/pins.sh"
# A version that is not the pin (the archive's program says another): refused.
sed -i 's/^PYTHON_VERSION=.*/PYTHON_VERSION=3.99.2/' "$KIT/pins.sh"
setup "a Python that is not the pinned version fails" 1 RUNNER_ENVIRONMENT=github-hosted -- python
cp "$T/pins.good" "$KIT/pins.sh"

# Never off GitHub's runners: the PC's path is untouched.
setup "on the PC (self-hosted): refused" 2 RUNNER_ENVIRONMENT=self-hosted -- python chromium zsh
if [ ! -s "$T/job/log/urls" ] && [ ! -s "$T/job/log/apt" ] && [ ! -s "$T/job/path" ]; then ok "setup: on the PC nothing is downloaded, installed or added"; else bad "setup: on the PC something ran"; fi
setup "where the runner's kind is unknown: refused" 2 -- python
# Jog, the trusted hosted service (#2467): its image has no Chromium, so it
# gets the same pinned tools as GitHub's; a lookalike is still refused.
JOG="RUNNER_ENVIRONMENT=self-hosted RUNNER_NAME=jog-0123abcd-0123456789ab JOG_RUNNER_SCOPE=1:1"
# shellcheck disable=SC2086 # $JOG is VAR=VALUE words on purpose
setup "Python, Chromium and zsh on Jog" 0 $JOG -- python chromium zsh
if [ "$(later chromium --version)" = "Google Chrome for Testing 999.0.1.2" ]; then ok "setup: on Jog a later step's chromium is the pinned Chrome for Testing"; else bad "setup: on Jog a later step's chromium says [$(later chromium --version)]"; fi
if [ "$(later python3 --version)" = "Python 3.99.1" ]; then ok "setup: on Jog a later step's python3 is the pinned one"; else bad "setup: on Jog a later step's python3 says [$(later python3 --version)]"; fi
setup "a Jog-named runner without Jog's scope: refused" 2 RUNNER_ENVIRONMENT=self-hosted RUNNER_NAME=jog-0123abcd-0123456789ab -- chromium
if [ ! -s "$T/job/log/urls" ] && [ ! -s "$T/job/path" ]; then ok "setup: on a Jog lookalike nothing is downloaded or added"; else bad "setup: on a Jog lookalike something ran"; fi
# setup()'s VAR=VALUE words can't hold a newline, so the multiline name (R1 on
# #2473) is passed through the environment of the same fake image.
rm -rf "$T/job" && mkdir -p "$T/job/tmp" "$T/job/log" "$T/job/bin"
: > "$T/job/path"; : > "$T/job/log/urls"
env -i PATH="$T/job/bin:$IMG/bin" HOME="$T/job" RUNNER_TEMP="$T/job/tmp" GITHUB_PATH="$T/job/path" \
  FAKE_LOG="$T/job/log" FAKE_SERVE="$IMG/serve" FAKE_BIN="$T/job/bin" \
  RUNNER_ENVIRONMENT=self-hosted JOG_RUNNER_SCOPE=1:1 RUNNER_NAME="impostor
jog-0123abcd-0123456789ab" "$IMG/bin/sh" "$KIT/setup.sh" chromium > "$T/job/said" 2>&1
status=$?
if [ "$status" = 2 ] && [ ! -s "$T/job/log/urls" ] && [ ! -s "$T/job/path" ]; then ok "setup: a multiline Jog name is refused, nothing downloaded"; else bad "setup: a multiline Jog name gave exit $status: $(tr '\n' ' ' < "$T/job/said")"; fi
setup "on arm64: no pinned build, refused" 2 RUNNER_ENVIRONMENT=github-hosted FAKE_ARCH=aarch64 -- python
setup "an unknown tool: usage" 2 RUNNER_ENVIRONMENT=github-hosted -- node
setup "no tool: usage" 2 RUNNER_ENVIRONMENT=github-hosted --

# The real pins are the PC's: ci.yml's pinned Python (the PC image's, which
# ci/runner/test.sh holds to the Dockerfile), and Chrome for Testing's format.
(
  # shellcheck source=pins.sh
  . "$HERE/pins.sh" 2> /dev/null || exit 1
  grep -qF "releases/download/$PYTHON_BUILD/cpython-$PYTHON_VERSION+$PYTHON_BUILD-" "$ROOT/.github/actions/docs-only/python.sh" || exit 1
  grep -qE "^ *x86_64\) sum=$PYTHON_SHA256 ;;$" "$ROOT/.github/actions/docs-only/python.sh" || exit 1
  printf '%s\n' "$CHROME_VERSION" | grep -qxE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' || exit 1
  printf '%s\n' "$CHROME_SHA256" | grep -qxE '[0-9a-f]{64}' || exit 1
) && ok "pins.sh: Python is ci.yml's pinned build; Chrome is a full version and SHA-256" || bad "pins.sh: missing, or not ci.yml's pinned Python"

# --- 3. cache.sh on GitHub's runners -----------------------------------------
U="$T/home"
mkdir -p "$U/.npm" "$T/store" "$T/cache-out"
echo old > "$U/.npm/file"
echo "not a cache" > "$T/store/npm.tar.zst"
said="$(env -i PATH="$PATH" HOME="$U" RUNNER_ENVIRONMENT=github-hosted CLOSEDWIZ_CACHE="$T/store" sh "$ROOT/ci/runner/cache.sh" restore npm "$U/.npm" 2>&1)"
if [ "$said" = "cache npm: a GitHub-hosted runner, so not the PC's store: nothing restored" ] && [ "$(cat "$U/.npm/file")" = old ]; then ok "cache.sh: on GitHub's runner a restore leaves the PC's store alone"; else bad "cache.sh: on GitHub's runner a restore said [$said]"; fi
said="$(env -i PATH="$PATH" HOME="$U" RUNNER_ENVIRONMENT=github-hosted CLOSEDWIZ_CACHE_OUT="$T/cache-out" CLOSEDWIZ_CACHE_AUDIENCE=a ACTIONS_ID_TOKEN_REQUEST_URL=u ACTIONS_ID_TOKEN_REQUEST_TOKEN=t sh "$ROOT/ci/runner/cache.sh" save npm "$U/.npm" 2>&1)"
if [ "$said" = "cache npm: a GitHub-hosted runner, so not the PC's store: nothing saved" ] && [ -z "$(ls -A "$T/cache-out")" ]; then ok "cache.sh: on GitHub's runner a save leaves nothing for a store"; else bad "cache.sh: on GitHub's runner a save said [$said]"; fi
said="$(env -i PATH="$PATH" HOME="$U" RUNNER_ENVIRONMENT=github-hosted sh "$ROOT/ci/runner/cache.sh" restore 'B@D' "$U/.npm" 2>&1)"
case "$said" in *usage*) ok "cache.sh: on GitHub's runner a bad name is still refused" ;; *) bad "cache.sh: on GitHub's runner a bad name said [$said]" ;; esac
said="$(env -i PATH="$PATH" HOME="$U" sh "$ROOT/ci/runner/cache.sh" restore npm "$U/.npm" 2>&1)"
if [ "$said" = "cache npm: no store on this runner, a cold start" ]; then ok "cache.sh: elsewhere unchanged (no store: a cold start)"; else bad "cache.sh: with no store it said [$said]"; fi

# --- 4. Every X5 lane, including shared setup/cache steps ---------------------
# Guard/setup/PC-store behavior above is unchanged. X5's workflow-boundary
# checker covers every discovered job rather than the old fixed counts.
if python3 -I "$ROOT/.github/actions/docs-only/test_workflow.py" Security; then
  ok "CI: every lane preserves fork routing, guard ordering and cache trust"
else bad "CI lane security wiring"; fi
if [ "$fails" = 0 ]; then echo "all ok"; else echo "$fails failed"; exit 1; fi
