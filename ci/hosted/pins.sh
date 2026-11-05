# The hosted setup's pins (#1265): the PC's, from ci/runner/Dockerfile
# (PYTHON_*, CHROME_*), so a job on GitHub's runner tests with the same
# Python and Chrome as on the PC. Change them there and here together;
# ci/hosted/test.sh holds Python to ci.yml's pinned build. x86-64 only.
# shellcheck disable=SC2034 # read by setup.sh
PYTHON_VERSION=3.13.18
PYTHON_BUILD=20261026
PYTHON_SHA256=df15fe60d3ff55bf9dcf25824b5572756bb8816ff93865a273d3301d7066a8b7
CHROME_VERSION=156.0.8078.47
CHROME_SHA256=e6c94490f0b6b337225aeb2d2a5034858516b7017356980ba94f5176d8774a50
