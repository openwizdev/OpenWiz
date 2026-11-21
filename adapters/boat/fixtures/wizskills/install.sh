#!/bin/sh
set -eu
[ "$1" = --version ] && [ "$3" = --dest ] || exit 2
[ -e "$4" ] && exit 0
git clone --quiet --depth 1 --branch "v$2" https://github.com/openwizdev/WizSkills.git "$4"
