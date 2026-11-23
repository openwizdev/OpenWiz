#!/bin/bash
set -eu
src=$1; fx=$2; home=$3
mkdir -p "$fx/bin" "$fx/drivers" "$fx/state" "$home/openwiz-live"
heads="hermes:2017:a823bb6f37e7b0ab9c681c0abefb04f803586e49 conductor:2020:921a7829db30e4684b477772fca6696e17a2b056
cursor:2021:e7ec81005d2d39d8cfe018acd631f543debcf7e9 factory:2022:aa83e218c459ed03102dac39d7f7d0a050f5d079
pane:2029:cd0e1aff8c8f8f752ed989dc0cfe79d7826ec108"
for h in $heads; do
  IFS=: read -r name pr sha <<<"$h"
  mkdir -p "$fx/drivers/$name"
  git -C "$src" archive "$sha" "adapters/$name/fixtures" | tar -x -C "$fx/drivers/$name" --strip-components=2
done
rm -rf "$fx/remote.git"; git init -q --bare "$fx/remote.git"
for h in $heads; do IFS=: read -r name pr sha <<<"$h"; git -C "$src" push -q "$fx/remote.git" "$sha:refs/heads/build-$name"; done
cat > "$fx/bin/gh" <<GH
case "\$1 \$2" in "auth status") echo "github.com: signed in (fixture)" >&2; exit 0;; esac
exec python3 -I "$src/kernel/live-rig/fixtures/heads/bin/gh" "\$@"
GH
cat > "$fx/bin/curl" <<CURL
for a in "\$@"; do case "\$a" in https://api.conductor.build*) exec "$fx/drivers/conductor/fixtures/bin/curl" "\$@";; esac; done
exec "$fx/drivers/cursor/fixtures/bin/curl" "\$@"
CURL
chmod +x "$fx/bin/gh" "$fx/bin/curl"
python3 -I - "$fx" "$heads" <<'PY'
import json, sys
fx, heads = sys.argv[1], sys.argv[2].split()
tickets = {'hermes': 1990, 'conductor': 1993, 'cursor': 1995, 'factory': 1999, 'pane': 2001}
out = {}
for i, h in enumerate(heads):
    name, pr, sha = h.split(':')
    out[str(tickets[name])] = [{'id': 5000 + i, 'user': {'login': 'openwiz[bot]'},
        'body': 'launch-fleet: look: live run due at the approved frozen head of #%s: %s' % (pr, sha)}]
json.dump(out, open(fx + '/comments.json', 'w'))
json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, open(fx + '/tracker.json', 'w'))
PY
python3 -I -c "import json,sys; json.dump({'hermes_home': sys.argv[1]+'/state/hermes', 'tracker': sys.argv[1]+'/tracker.json',
  'turns': sys.argv[1]+'/state/hermes-turns', 'hold': sys.argv[1]+'/state/hermes-hold', 'envs': sys.argv[1]+'/state/hermes-envs'},
  open(sys.argv[2]+'/.fake-hermes.json', 'w'))" "$fx" "$home"
echo '{"repo": "example/site", "ticket": 7}' > "$home/openwiz-live/settings.json"
