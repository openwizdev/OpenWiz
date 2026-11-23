import re

from check import git, require


def repository(repo):
    raw = git(repo, 'config', '--get-all', 'remote.origin.url').decode().splitlines()
    require(len(raw) == 1, 'one origin URL is required')
    match = re.fullmatch(r'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)'
                         r'([A-Za-z0-9-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?', raw[0])
    require(match is not None, 'origin must name one GitHub repository without credentials')
    name = match[1]
    require(all(part not in {'.', '..'} for part in name.split('/')), 'invalid origin repository')
    return name


def remote_url(name):
    return 'https://github.com/' + name + '.git'
