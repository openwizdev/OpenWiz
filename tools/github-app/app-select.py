#!/usr/bin/env python3
USAGE = """The pairing App selector (#2661): pick one App's state on the owner's machine and
hand the mint to the token service there, under contracts/token-service.v1.md.

  app-select.py mint   read one token-service request on stdin, choose one App
                       state directory, run `token-service.py mint --state-dir`
                       on it and pass its one JSON line and exit back unchanged

The owner points OPENWIZ_TOKEN_SERVICE at this file. Its config,
OPENWIZ_APP_SELECT_CONFIG or ~/.config/openwiz/app-select.json, is a regular file the
owner owns with no group or other permission bits (0600 or 0400, say), holding one of:

  {"state_dir": "/abs/state"}                named: that App, and only it
  {"routes": [{"repository": "owner/*", "state_dir": "/abs/a"},
              {"repository": "owner/name", "state_dir": "/abs/b"}]}
                                             route map: each requested repository
                                             takes its first matching route, and
                                             all of them must land on one state

An invalid request gets the service's own usage or one-owner refusal before any
service call. A missing, unsafe or unclear config, a repository no route matches or
a request split across two states is the contract's refusal with one fixed sentence
on stderr: no service call and no token. The selector opens no key, asks GitHub
nothing and never touches the default state.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import app  # noqa: E402 -- the documented `python3 -I` drops this folder from sys.path

SERVICE = HERE / "token-service.py"
_spec = importlib.util.spec_from_file_location("token_service", SERVICE)
service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(service)

CONFIG, CONFIG_LIMIT, BUDGET_S = "OPENWIZ_APP_SELECT_CONFIG", 4096, 55
SENTENCE = ("App selector refused: set OPENWIZ_APP_SELECT_CONFIG (default ~/.config/openwiz/app-select.json) "
            "to a file you own with no group or other permission bits, naming one App state as \"state_dir\", "
            "or \"routes\" that map every requested repository to the same App state.")


def config_path():
    if os.environ.get(CONFIG):
        return Path(os.environ[CONFIG])
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", ""))
    return (xdg if xdg.is_absolute() else Path.home() / ".config") / "openwiz/app-select.json"


def app_state(value):
    app.require(isinstance(value, str))
    path = app.state_path(Path(value))
    os.close(app.app_directory(path))
    return path


def pattern(value):
    app.require(isinstance(value, str))
    owner, _, name = value.partition("/")
    app.require(name == "*" and app.REPOSITORY.fullmatch(owner + "/x") is not None or
                app.REPOSITORY.fullmatch(value) is not None and name not in (".", ".."))
    return value.lower()


def configured():
    path = config_path()
    app.require(path.is_absolute())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        app.checked(fd)
        app.require(os.fstat(fd).st_size <= CONFIG_LIMIT)
        value = app.parse_json(os.read(fd, CONFIG_LIMIT + 1).decode("utf-8"))
    finally:
        os.close(fd)
    if set(value) == {"state_dir"}:
        return [("*", app_state(value["state_dir"]))]
    app.require(set(value) == {"routes"} and isinstance(value["routes"], list) and value["routes"])
    for route in value["routes"]:
        app.require(isinstance(route, dict) and set(route) == {"repository", "state_dir"})
    return [(pattern(route["repository"]), app_state(route["state_dir"])) for route in value["routes"]]


def route(routes, repositories):
    chosen = set()
    for name in repositories:
        owner = name.split("/")[0].lower() + "/*"
        found = [state for match, state in routes if match in ("*", owner, name.lower())]
        if not found:
            return None
        chosen.add(found[0])
    return chosen


def refuse(code, sentence=True):
    if sentence:
        print(SENTENCE, file=sys.stderr)
    return service.answer(service.refusal(code), service.REFUSALS[code][0])


def main():
    parser = argparse.ArgumentParser(description=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("mint",))
    parser.add_argument("--api-base", default="https://api.github.com",
                        help="GitHub API; HTTP loopback accepted for synthetic tests only")
    args = parser.parse_args()
    base = app.api_base(args.api_base)
    data = sys.stdin.buffer.read(service.REQUEST_LIMIT + 1)
    try:
        repositories = service.request_of(data)["repositories"]
    except service.Refused:
        return refuse("usage", sentence=False)
    if len({name.split("/")[0].lower() for name in repositories}) != 1:
        return refuse("one-owner", sentence=False)
    try:
        states = route(configured(), repositories)
    except Exception:
        return refuse("unavailable")
    if not states:
        return refuse("not-installed")
    if len(states) != 1:
        return refuse("unavailable")
    try:
        done = subprocess.run([sys.executable, "-I", str(SERVICE), "mint", "--state-dir", str(states.pop()),
                               "--api-base", base], input=data, stdout=subprocess.PIPE, timeout=BUDGET_S)
    except (OSError, subprocess.TimeoutExpired):
        return service.answer(service.refusal("unavailable"), 1)
    sys.stdout.buffer.write(done.stdout)
    sys.stdout.flush()
    return done.returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        # SECURITY: never a traceback: it could carry a request, a path or a provider body.
        sys.exit(service.answer(service.refusal("unavailable"), 1))
