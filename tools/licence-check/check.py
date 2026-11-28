#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys


ORGANIZATION = "openwizdev"
TRACKER = "openwizdev/OpenWiz"
EXPECTED = "Apache-2.0"
REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+")
SPDX = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
HTTP_STATUS = re.compile(r"HTTP/\d+(?:\.\d+)? (\d{3})(?: .*)?")


class AuditError(Exception):
    pass


def gh(method, *args):
    try:
        return subprocess.run(
            ["gh", "api", "--hostname", "github.com", "--method", method, *args],
            capture_output=True, encoding="utf-8", timeout=90, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise AuditError("could not read the GitHub CLI response") from None


def decode(raw, operation):
    try:
        return json.loads(raw)
    except ValueError:
        raise AuditError(f"{operation}: invalid JSON response") from None


def get(endpoint, operation, *, paginated=False):
    options = ("--paginate", "--slurp") if paginated else ()
    result = gh("GET", *options, endpoint)
    if result.returncode:
        raise AuditError(f"{operation}: GitHub read failed")
    return decode(result.stdout, operation)


def pages(endpoint, operation):
    data = get(endpoint, operation, paginated=True)
    if not isinstance(data, list) or not data:
        raise AuditError(f"{operation}: invalid pages")
    for page in data:
        if not isinstance(page, list):
            raise AuditError(f"{operation}: invalid page")
        for row in page:
            if not isinstance(row, dict):
                raise AuditError(f"{operation}: invalid row")
            yield row


def public_repositories(organization):
    endpoint = f"orgs/{organization}/repos?type=public&per_page=100"
    repositories = {}
    for row in pages(endpoint, "repository list"):
        if row.get("private") is True:
            continue
        name = row.get("full_name")
        if row.get("private") is not False or not isinstance(name, str):
            raise AuditError("repository list: invalid visibility or name")
        owner, _, repo = name.partition("/")
        if owner.lower() != organization.lower() or not REPO_NAME.fullmatch(repo) or repo in {".", ".."}:
            raise AuditError("repository list: unexpected repository name")
        repositories.setdefault(name.lower(), name)
    return [repositories[key] for key in sorted(repositories)]


def licence_spdx(repository):
    operation = f"{repository} licence"
    response = gh("GET", "--include", f"repos/{repository}/license")
    headers, separator, body = response.stdout.partition("\n\n")
    status = HTTP_STATUS.fullmatch(headers.partition("\n")[0])
    code = status[1] if status else None
    if code == "404" and separator and response.returncode:
        metadata = get(f"repos/{repository}", f"{repository} visibility")
        if (not isinstance(metadata, dict) or metadata.get("private") is not False
                or metadata.get("full_name") != repository):
            raise AuditError(f"{operation}: repository visibility could not be confirmed")
        return None
    if response.returncode or code != "200" or not separator:
        raise AuditError(f"{operation}: GitHub read failed" + (f" (HTTP {code})" if code else ""))

    data = decode(body, operation)
    if not isinstance(data, dict) or "license" not in data:
        raise AuditError(f"{operation}: invalid licence metadata")
    licence = data["license"]
    if licence is None:
        return None
    if not isinstance(licence, dict) or "spdx_id" not in licence:
        raise AuditError(f"{operation}: invalid SPDX metadata")
    spdx = licence["spdx_id"]
    if spdx is not None and (not isinstance(spdx, str) or not SPDX.fullmatch(spdx)):
        raise AuditError(f"{operation}: invalid SPDX identifier")
    return spdx


def open_titles(endpoint):
    titles = set()
    for row in pages(f"{endpoint}?state=open&per_page=100", "open issue list"):
        if "pull_request" in row:
            continue
        title = row.get("title")
        if not isinstance(title, str):
            raise AuditError("open issue list: invalid title")
        titles.add(title)
    return titles


def file_issues(tracker, gaps):
    endpoint = f"repos/{tracker}/issues"
    titles = open_titles(endpoint)
    for repository, spdx in gaps:
        title = f"licence: {repository} is not {EXPECTED}"
        if title in titles:
            continue
        body = (f"GitHub's licence API reported `{spdx or 'none'}` for [{repository}]"
                f"(https://github.com/{repository}). Check the repository against the {EXPECTED} requirement.")
        result = gh("POST", endpoint, "-f", f"title={title}", "-f", f"body={body}")
        if result.returncode:
            raise AuditError(f"{repository}: issue creation could not be confirmed")
        titles.add(title)


def main(argv=None, *, organization=ORGANIZATION, tracker=TRACKER):
    parser = argparse.ArgumentParser(
        description="Audit public OpenWiz repositories against GitHub's detected licence.",
    )
    parser.add_argument("--file-issues", action="store_true", help="file gaps as OpenWiz issues")
    args = parser.parse_args(argv)
    try:
        rows = [(repository, licence_spdx(repository)) for repository in public_repositories(organization)]
        gaps = [(repository, spdx) for repository, spdx in rows if spdx != EXPECTED]
        print("repository\tspdx\tresult")
        for repository, spdx in rows:
            result = "pass" if spdx == EXPECTED else "fail"
            print(f"{repository}\t{spdx or 'none'}\t{result}")
        if args.file_issues and gaps:
            file_issues(tracker, gaps)
    except AuditError as exc:
        print(f"licence check: {exc}", file=sys.stderr)
        return 2
    return int(bool(gaps))


if __name__ == "__main__":
    sys.exit(main())
