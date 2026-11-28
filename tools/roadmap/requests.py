import re

SCOPE_REPOS = ("openwizdev/OpenWiz", "openwizdev/WizSkills", "openwizdev/WizMarket")
SCOPE_BY_LOWER = {repo.lower(): repo for repo in SCOPE_REPOS}
ISSUE_STATES = ("open", "closed")
KINDS = ("bug", "driver", "feature", "docs")
TOP_LIMIT = 10

SPEC_ISSUES_JQ = (".[] | select(.pull_request == null)"
                  " | {number, title, state, sub_issues: .sub_issues_summary.total, html_url}")
REQUESTS_JQ = (".[] | select(.pull_request == null)"
               " | {number, title, state, body, html_url, plus_one: .reactions[\"+1\"]}")

MARKER_RE = re.compile(r"OpenWiz subscriber request operation [0-9a-f]{32}")
MILESTONE_URL_RE = re.compile(r"(https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+)/milestone/[1-9][0-9]*")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def number(v):
    return type(v) is int and v > 0


def nonneg(v):
    return type(v) is int and v >= 0


def string(v):
    return type(v) is str


def validate_scope_repo(value):
    if not isinstance(value, str):
        raise ValueError(f"{value!r} is not an allowed scope repository")
    canonical = SCOPE_BY_LOWER.get(value.lower())
    if canonical is None:
        allowed = ", ".join(SCOPE_REPOS)
        raise ValueError(f"{value!r} is not an allowed scope repository ({allowed})")
    return canonical


def resolve_scope_repos(repos):
    if not repos:
        return SCOPE_REPOS
    seen, out = set(), []
    for repo in repos:
        canonical = validate_scope_repo(repo)
        if canonical not in seen:
            seen.add(canonical)
            out.append(canonical)
    return tuple(out)


def parse_public_request(body):
    if not isinstance(body, str) or not body:
        return None
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    lines = text.split("\n")
    if len(lines) < 5 or lines[-2] != "" or MARKER_RE.fullmatch(lines[-1]) is None:
        return None
    try:
        blank = lines.index("")
    except ValueError:
        return None
    if blank == 0 or blank >= len(lines) - 2:
        return None
    header = lines[:blank]
    if len(header) == 1:
        visibility = "public"
    elif len(header) == 2 and header[1] == "Visibility: public":
        visibility = "public"
    else:
        return None
    kind_line = header[0]
    if not kind_line.startswith("Kind: "):
        return None
    kind = kind_line[len("Kind: "):]
    if kind not in KINDS:
        return None
    prose = lines[blank + 1 : -2]
    if not any(line.strip() for line in prose):
        return None
    return {"kind": kind, "visibility": visibility}


def safe_title(title):
    cleaned = " ".join(CONTROL_RE.sub(" ", title).split())
    if not cleaned:
        return None
    cleaned = cleaned.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return cleaned.replace("<", "&lt;").replace(">", "&gt;")


def issue_url_matches(html_url, repo_url, issue_number):
    expected = f"{repo_url}/issues/{issue_number}"
    return isinstance(html_url, str) and html_url.lower() == expected.lower()


def read_specs(root, versions, run_gh, parse_objects, fail_cls):
    specs = []
    for v in versions:
        if v["state"] != "building":
            continue
        match = MILESTONE_URL_RE.fullmatch(v["html_url"])
        if match is None:
            raise fail_cls(f"milestone {v['title']}'s html_url is not a GitHub milestone URL")
        repo_url = match.group(1)
        items = parse_objects(
            run_gh(root, f"repos/{{owner}}/{{repo}}/issues?milestone={v['number']}&state=open&per_page=100",
                   SPEC_ISSUES_JQ),
            f"milestone {v['title']}'s open specs",
            {"number": number, "title": string, "state": lambda s: s in ISSUE_STATES,
             "sub_issues": nonneg, "html_url": string})
        found = []
        for item in items:
            if not issue_url_matches(item["html_url"], repo_url, item["number"]):
                raise fail_cls(f"milestone {v['title']}'s open specs: unexpected html_url for #{item['number']}")
            if item["state"] != "open" or item["sub_issues"] <= 0:
                continue
            title = safe_title(item["title"])
            if title is None:
                raise fail_cls(f"milestone {v['title']}'s open specs: empty title for #{item['number']}")
            found.append({
                "version": v["title"],
                "number": item["number"],
                "title": title,
                "html_url": item["html_url"],
            })
        found.sort(key=lambda item: item["number"])
        specs.extend(found)
    return specs


def read_requests(root, scope_repos, run_gh, parse_objects, fail_cls, limit=TOP_LIMIT):
    try:
        repos = resolve_scope_repos(scope_repos)
    except ValueError as e:
        raise fail_cls(str(e)) from None
    found = []
    for repo in repos:
        repo_url = f"https://github.com/{repo}"
        items = parse_objects(
            run_gh(root, f"repos/{repo}/issues?state=open&per_page=100", REQUESTS_JQ),
            f"{repo}'s open issues",
            {"number": number, "title": string, "state": lambda s: s in ISSUE_STATES,
             "body": lambda b: b is None or string(b), "html_url": string, "plus_one": nonneg})
        for item in items:
            if not issue_url_matches(item["html_url"], repo_url, item["number"]):
                raise fail_cls(f"{repo}'s open issues: unexpected html_url for #{item['number']}")
            if item["state"] != "open":
                continue
            if parse_public_request(item["body"]) is None:
                continue
            title = safe_title(item["title"])
            if title is None:
                continue
            found.append({
                "repo": repo,
                "number": item["number"],
                "title": title,
                "html_url": item["html_url"],
                "plus_one": item["plus_one"],
            })
    return rank_requests(found, limit=limit)


def rank_requests(items, limit=TOP_LIMIT):
    ranked = sorted(items, key=lambda item: (-item["plus_one"], item["repo"].lower(), item["number"]))
    return ranked[:limit]


def specs_section(specs):
    out = ["", "## Specs in progress", ""]
    for spec in specs:
        out.append(f"- **{spec['version']}**: [{spec['title']}]({spec['html_url']})")
    if not specs:
        out.append("- None right now.")
    return out


def most_wanted_section(items):
    out = ["", "## Most wanted", ""]
    for item in items:
        count = item["plus_one"]
        unit = "+1" if count == 1 else "+1s"
        out.append(f"- [{item['title']}]({item['html_url']}) — {count} {unit}")
    if not items:
        out.append("- None right now.")
    return out
