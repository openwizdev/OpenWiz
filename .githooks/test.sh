#!/bin/sh
set -eu
case "$#:${1:-}" in
  0:|1:--fixtures-only) ;;
  *) echo "usage: sh .githooks/test.sh [--fixtures-only]" >&2; exit 2 ;;
esac

root="$(cd "$(dirname "$0")/.." && pwd -P)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$tmp/gitconfig"
git config --global user.name synthetic
git config --global user.email synthetic@users.noreply.github.com

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

work="$tmp/work"
remote="$tmp/remote.git"
git init -q -b main "$work"
git init -q --bare "$remote"
git -C "$work" commit --allow-empty -qm 'Synthetic root'
public_root="$(git -C "$work" rev-parse HEAD)"
git -C "$work" commit --allow-empty -qm 'Synthetic anchor'
base="$(git -C "$work" rev-parse HEAD)"
git -C "$remote" fetch -q "$work" 'HEAD:refs/heads/topic' 'HEAD:refs/heads/keep'

mkdir -p "$tmp/.githooks" "$tmp/tools/privacy-check"
cp "${PRE_PUSH_HOOK:-$root/.githooks/pre-push}" "$tmp/.githooks/pre-push"
chmod +x "$tmp/.githooks/pre-push"
cp "$root"/tools/privacy-check/*.py "$tmp/tools/privacy-check/"
sed -e "s/^PUBLIC_ROOT = .*/PUBLIC_ROOT = '$public_root'/" \
    -e "s/^PUBLIC_ANCHOR = .*/PUBLIC_ANCHOR = '$base'/" \
    "$root/tools/privacy-check/check.py" > "$tmp/tools/privacy-check/check.py"
git -C "$work" config core.hooksPath "$tmp/.githooks"

cat > "$tmp/fixture-ssh" <<'SSH'
#!/bin/sh
exec git receive-pack "$FIXTURE_REMOTE"
SSH
chmod +x "$tmp/fixture-ssh"
unset GIT_SSH_COMMAND
export FIXTURE_REMOTE="$remote" GIT_SSH="$tmp/fixture-ssh" GIT_SSH_VARIANT=simple
git -C "$work" remote add fixture 'ssh://synthetic.invalid/fixture.git'
export OPENWIZ_PRIVACY_LITERALS="$tmp/literals"
literal='synthetic confidential sample for hook proof'
printf '%s\n' "$literal" > "$OPENWIZ_PRIVACY_LITERALS"

mkdir -p "$work/docs"
printf '%s\n' 'Synthetic clean change' > "$work/docs/change.txt"
git -C "$work" add docs/change.txt
git -C "$work" commit -qm 'Clean docs change'
clean="$(git -C "$work" rev-parse HEAD)"
git -C "$work" push fixture HEAD:refs/heads/topic ||
  fail 'a clean ref update must succeed without build dependencies'
[ "$(git -C "$remote" rev-parse refs/heads/topic)" = "$clean" ] ||
  fail 'the clean push did not update topic'
echo 'ok: clean ref update without build dependencies'

printf '%s\n' "$literal" > "$work/planted.txt"
git -C "$work" add planted.txt
git -C "$work" commit -qm 'Plant a synthetic private literal'
if git -C "$work" push fixture "$clean:refs/heads/keep" HEAD:refs/heads/topic > "$tmp/refusal" 2>&1; then
  fail 'a private literal must stop the whole push'
fi
grep -q '^T3 ' "$tmp/refusal" || { cat "$tmp/refusal" >&2; fail 'expected a private literal finding'; }
[ "$(git -C "$remote" rev-parse refs/heads/keep)" = "$base" ] ||
  fail 'the refused push changed keep'
[ "$(git -C "$remote" rev-parse refs/heads/topic)" = "$clean" ] ||
  fail 'the refused push changed topic'
echo 'ok: a private literal stops both ref updates'

OPENWIZ_PRIVACY_LITERALS="$tmp/missing" git -C "$work" push fixture :refs/heads/topic ||
  fail 'deleting a ref must succeed without scanning'
status=0
git -C "$remote" show-ref --verify --quiet refs/heads/topic || status=$?
[ "$status" -eq 1 ] || fail 'the remote topic ref was not deleted'
[ "$(git -C "$remote" rev-parse refs/heads/keep)" = "$base" ] ||
  fail 'the deletion changed keep'
echo 'ok: deletion removes only the named ref'

git -C "$work" reset --hard -q "$clean"
personal_email='robin''@''mail.invalid'
GIT_AUTHOR_EMAIL="$personal_email" git -C "$work" commit --allow-empty -qm 'Personal author email'
if git -C "$work" push fixture HEAD:refs/heads/keep > "$tmp/refusal" 2>&1; then
  fail 'a personal author email must stop the push'
fi
grep -q '^C3 commit-1-author:1$' "$tmp/refusal" || { cat "$tmp/refusal" >&2; fail 'expected C3 author refusal'; }
! grep -Fq "$personal_email" "$tmp/refusal" || { cat "$tmp/refusal" >&2; fail 'refusal leaked author email'; }

git -C "$work" reset --hard -q "$clean"
GIT_COMMITTER_EMAIL="$personal_email" git -C "$work" commit --allow-empty -qm 'Personal committer email'
if git -C "$work" push fixture HEAD:refs/heads/keep > "$tmp/refusal" 2>&1; then
  fail 'a personal committer email must stop the push'
fi
grep -q '^C3 commit-1-committer:1$' "$tmp/refusal" || { cat "$tmp/refusal" >&2; fail 'expected C3 committer refusal'; }
! grep -Fq "$personal_email" "$tmp/refusal" || { cat "$tmp/refusal" >&2; fail 'refusal leaked committer email'; }

git -C "$work" reset --hard -q "$clean"
GIT_AUTHOR_EMAIL='41898282+synthetic-bot[bot]@users.noreply.github.com' \
  GIT_COMMITTER_EMAIL='noreply@github.com' \
  git -C "$work" commit --allow-empty -qm 'Bot author with GitHub web-flow committer'
git -C "$work" push fixture HEAD:refs/heads/keep ||
  fail 'bot author with GitHub web-flow committer must pass'
echo 'ok: commit email checks enforce noreply, bot and web-flow committer rules'
