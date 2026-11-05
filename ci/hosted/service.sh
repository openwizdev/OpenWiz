# Whose runner this is (#2467), for guard.sh and setup.sh: sourced, not run.
#   runner_service   prints github, jog or none
# github: one of GitHub's own runners (RUNNER_ENVIRONMENT=github-hosted).
# jog: the one trusted hosted service, Jog: a self-hosted runner named
#   exactly jog-<8 hex>-<12 hex> (one line, no CR or LF) whose runner sets
#   JOG_RUNNER_SCOPE, as Jog's do.
# none: anything else (the PC, Namespace, an unknown kind).
# Only GitHub's own runners are trusted with a fork's pull request; this
# names who may use GitHub's cache and the pinned hosted setup.
runner_service() {
  case "${RUNNER_ENVIRONMENT:-}" in
    github-hosted) echo github ;;
    self-hosted)
      # The whole name, one line: grep -x matches each line, so a name with a
      # line break is refused before it is matched (R1 on #2473).
      name="${RUNNER_NAME:-}" cr="$(printf '\r')"
      case "$name" in
        *"$cr"* | *'
'*) echo none ;;
        *) if [ -n "${JOG_RUNNER_SCOPE:-}" ] &&
          printf '%s\n' "$name" | grep -Eqx 'jog-[0-9a-f]{8}-[0-9a-f]{12}'; then
          echo jog
        else echo none; fi ;;
      esac ;;
    *) echo none ;;
  esac
}
