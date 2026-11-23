#!/bin/sh
STUBS=$(mktemp -d)
for cli in claude codex cursor-agent agent cursor pi opencode copilot goose gemini kimi qwen cline kilo kilocode crush \
    vibe auggie kiro-cli junie amp agy oz sculpt hermes acpx droid boat room-cli runpane pane openhands devin warp grok \
    codespaces conductor; do
  printf '#!/bin/sh\necho "%s: refused, the rehearsal never starts an agent CLI" >&2\nexit 1\n' "$cli" > "$STUBS/$cli"
  chmod +x "$STUBS/$cli"
done
export PATH="$STUBS:$PATH"
