from html import unescape
from html.parser import HTMLParser
from pathlib import PurePosixPath
import posixpath
import re
from urllib.parse import unquote, urlsplit

import os

from check import require, Refused, alias, blob, changelog_entry, git, refuse_ranges, sha

LABELS = {"fixture-tested", "live-observation", "source-inspection", "unverified", "proposal", "context"}
PUBLIC_HOSTS = {"github.com", "raw.githubusercontent.com", "doc.rust-lang.org", "rust-lang.org",
                "crates.io", "registry.npmjs.org", "www.apache.org", "apache.org", "spdx.org",
                "nextjs.org", "react.dev", "nodejs.org", "cloudroom.dev", "www.cloudroom.dev",
                "developers.cloudflare.com", "cloudflare.com", "www.cloudflare.com",
                "trycloudflare.com", "cloudflareaccess.com", "127.0.0.1", "localhost"}


def claim_documents(check):
    docs = {}
    for path,text in check.texts.items():
        if path.endswith(".md"):
            docs[path] = text
    return docs


PRIVATE_REPOSITORY = "https://github.com/jparker2006/ClosedWiz"
PRIVATE_REFERENCE = re.compile(re.escape(PRIVATE_REPOSITORY) + r"/(?:issues|pull)/[1-9][0-9]*(?:#issuecomment-[1-9][0-9]*)?")
POINTER = re.escape(PRIVATE_REPOSITORY) + r"/(?:issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*"


def record_spans(text, public_repo):
    spans = []
    for match in re.finditer(r"(?<![!\\])\[private record\]\(("+POINTER+r")\)",text):
        spans.append((*match.span(),match[1]))
    for match in re.finditer(r"^(?:Private record: )?("+POINTER+r")$",text,re.M):
        spans.append((*match.span(),match[1]))
    was = r"^was \[ClosedWiz #([1-9][0-9]*)\]\(("+re.escape(PRIVATE_REPOSITORY)+r"/(?:issues|pull)/\1)\)$"
    for match in re.finditer(was,text,re.M):
        spans.append((*match.span(),match[2]))
    public_names = {"https://github.com/"+public_repo,
                    PRIVATE_REPOSITORY.replace("ClosedWiz","OpenWiz"),
                    "https://github.com/openwizdev/OpenWiz",
                    "https://github.com/openwizdev/openwiz"}
    targets = "(?:"+"|".join(re.escape(name) for name in sorted(public_names))+")"
    moved = r"^moved to \[OpenWiz #([1-9][0-9]*)\]\(("+targets+r"/(?:issues|pull)/\1)\)$"
    for match in re.finditer(moved,text,re.M):
        spans.append((*match.span(),match[2]))
    return spans


def mask_records(text, spans):
    for start,end,_ in sorted(spans,reverse=True):
        text = text[:start]+" "*(end-start)+text[end:]
    return text


def url_public(url, reviewed=False, record=False):
    parsed = urlsplit(url)
    require(parsed.scheme in {"http", "https"}, "private-link: unknown scheme")
    host = parsed.hostname or ""
    reserved = host.endswith((".example", ".invalid")) or host == "example.com"
    require((parsed.username is None and parsed.password is None)
            or (reviewed and (reserved or (bool(parsed.username) and parsed.password is None))),
            "private-link: URL credentials")
    require(not re.search(r"closedwiz|/private/|/" r"Users/|/" r"home/",unquote(url),re.I)
            or (record and PRIVATE_REFERENCE.fullmatch(url)), "private-link: private URL")
    require(reviewed or host in PUBLIC_HOSTS or reserved,
            "private-link: unreviewed host")


def decoded_url(url):
    return unquote(unescape(url))


def reviewed_url(check, path, url, used=None, record=False):
    matches = [i for i,e in enumerate(check.plan.get("scan_exceptions",[]))
               if e["path"] == path and e["rule"] == "url" and e["value"] == url]
    url_public(decoded_url(url), reviewed=bool(matches), record=record)
    if used is not None:
        used.update(matches)


def public_literal(path, text, match, rule):
    value = match.group()
    suffix = PurePosixPath(path).suffix.lower()
    if rule == "identifier" and suffix == ".rs":
        return value in {"env_host", "env_remove", "env_clear"}
    if rule == "personal" and value == "settings.local" and PurePosixPath(path).name == ".gitignore":
        line = text[text.rfind("\n", 0, match.start())+1:].split("\n", 1)[0].strip()
        return line in {"settings.local", ".claude/settings.local.json", "/.claude/settings.local.json"}
    if rule != "internal" or not re.fullmatch(r"#(?:[0-9]{3}|[0-9]{4}|[0-9]{6}|[0-9]{8})", value):
        return False
    if not re.match(r"(?:$|[\s;,\"')}>/])", text[match.end():]):
        return False
    prefix = text[:match.start()]
    if prefix.rfind("/*") > prefix.rfind("*/") or prefix.rfind("<!--") > prefix.rfind("-->"):
        return False
    if suffix in {".svg", ".html"}:
        tag = prefix[prefix.rfind("<"):]
        if re.fullmatch(r"<[A-Za-z][^<>]*", tag):
            if re.search(r"(?<![\w-])(?:color|fill|stroke|stop-color|flood-color|lighting-color)\s*=\s*['\"]$", tag, re.I):
                return True
            style = re.search(r"(?<![\w-])style\s*=\s*(['\"])((?:(?!\1).)*)$", tag, re.I|re.S)
            if not style:
                return False
            prefix = style[2]
        else:
            style = re.search(r"<style\b[^>]*>([^<]*)$", prefix, re.I)
            if not style:
                return False
            prefix = style[1]
    if suffix in {".css", ".svg", ".html"}:
        return bool(re.search(r"(?:^|[;{])\s*(?:--[\w-]+|[\w-]*color|background|fill|stroke|border(?:-(?:top|right|bottom|left))?|outline|box-shadow|text-shadow)\s*:\s*[^;{}'\"<>]*$", prefix, re.I))
    if suffix not in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}:
        return False
    if "//" in prefix.rsplit("\n", 1)[-1]:
        return False
    style = re.search(r"\b(?:[\w-]*color|background|fill|stroke)\s*[:=]\s*(['\"])$", prefix, re.I)
    if not style or not text[match.end():].startswith(style[1]):
        return False
    tokens = (
        r"//[^\n]*|/\*[\s\S]*?(?:\*/|$)"
        r"|\"(?:\\.|[^\"\\])*(?:\"|$)|'(?:\\.|[^'\\])*(?:'|$)"
        r"|`(?:\\.|[^`\\])*(?:`|$)"
        r"|/(?:\\.|[^/\\[]|\[(?:\\.|[^\]\\])*(?:\]|$))*(?:/|$)"
    )
    return not any(token.start() <= style.start() < token.end()
                   for token in re.finditer(tokens, prefix))


def scan(check):
    from repository import repository
    public_repo = repository(check.args.repo)
    texts = {}
    exceptions = check.plan.get("scan_exceptions",[])
    used = set()
    known_hex = set()
    for item in check.report["files"]:
        if item["path"] == "Cargo.lock":
            lock = (check.export/item["path"]).read_text()
            known_hex.update(re.findall(r'^checksum = "([0-9a-f]{64})"$',lock,re.M))
    for index,exception in enumerate(exceptions):
        match = next((f for f in check.report["files"] if f["path"] == exception["path"]),None)
        require(match and match["sha256"] == exception["sha256"], "stale scan exception")
        require(not any(exception == e for e in exceptions[:index]), "duplicate scan exception")
        if exception["rule"] == "url":
            record = exception["path"].endswith(".md") and any(
                url == exception["value"] for _,_,url in record_spans(
                    (check.export/exception["path"]).read_text(),public_repo))
            url_public(unquote(unescape(exception["value"])),reviewed=True,record=record)
    paths = {f["path"] for f in check.report["files"]}
    for item in check.report["files"]:
        path = item["path"]
        if item["mode"] == "120000":
            target = os.readlink(check.export/path).encode()
            require(sha(target) == item["sha256"], "staged hash changed")
            alias(path,target,paths)
            continue
        data = (check.export/path).read_bytes()
        require(sha(data) == item["sha256"], "staged hash changed")
        try:
            text = data.decode("utf-8")
            require("\0" not in text,"binary")
        except (UnicodeError, Refused):
            assets = [i for i,e in enumerate(exceptions) if e["path"] == path and e["rule"] == "release-asset"]
            if assets:
                require(len(assets) == 1, "release-asset: repeated review")
                review = exceptions[assets[0]]
                match = re.fullmatch(r"(0\.[0-9]+\.[0-9]+)@([0-9a-f]{40})@(aarch64-apple-darwin|x86_64-apple-darwin|aarch64-unknown-linux-gnu|x86_64-unknown-linux-gnu)", review["value"])
                require(match and match[1] == check.args.version
                        and path == f"packages/openwiz-{match[1]}-{match[3]}.tar.gz",
                        "release-asset: exact version/source/target review required")
                used.update(assets)
                continue
            try:
                old = blob(check.args.public_repo,check.plan["public_base"],path)
            except Refused:
                old = b""
            require(old == data and data, f"binary: new or changed asset {path}")
            continue
        texts[path] = text
        spans = record_spans(text,public_repo) if path.endswith(".md") else []
        for _,_,url in spans:
            reviewed_url(check,path,url,used,record=True)
        text = mask_records(text,spans)
        decoded = decoded_url(text)
        if path.endswith(".json"):
            import json
            try:
                decoded += "\n"+str(json.loads(text))
            except ValueError as error:
                reviewed = [i for i,e in enumerate(exceptions)
                            if e["path"] == path and e["rule"] == "invalid-json" and e["value"] == path]
                if not reviewed:
                    raise Refused(f"invalid JSON: {path}") from error
                used.update(reviewed)
        checks = {
            "secret":r"gh[opsur]_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9]+|\bsk-[A-Za-z0-9]{10,}|xox[abp]-|AKIA[0-9A-Z]{12,}|BEGIN [A-Z ]*PRIVATE KEY|(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[\"'][^\"']{6,}",
            "personal":r"/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|[A-Za-z0-9._%+-]+@(?![A-Za-z0-9.-]*\.(?:invalid|example)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\b[A-Za-z0-9-]+\.local\b|[A-Z]:\\[A-Za-z]",
            "secret-hex":r"\b[0-9a-f]{32,}\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            "identifier":r"\b(?:(?i:(?:thr|prj|mch|evt|usr|acct|ses|org)_(?!(?:syn|web)(?:_|\b))[A-Za-z0-9][A-Za-z0-9_-]*)|env_(?!(?:syn|web)(?:_|\b))[A-Za-z0-9][A-Za-z0-9-]*(?![\w-]))",
            "internal":r"closedwiz|"+"|".join(re.escape(term) for term in check.literals)+r"|\b(?:Sol|Haiku)\s+(?:round|review|finding)|\bticket\s+\d+|\bPR\s*#?\d+|private/|\bWS-\d+|approval sheet|(?<![\w&])#\d+\b",
        }
        _,_,destinations = markdown_links(text) if path.endswith((".md", ".html", ".svg")) else ({},[],[])
        urls = []
        masked = text
        for url,start,end in sorted(destinations,key=lambda item:item[1],reverse=True):
            url = decoded_url(url)
            if urlsplit(url).scheme in {"http", "https"}:
                urls.append(url)
                urls.extend(match.group() for match in re.finditer(r"https?://[^\s<>\"'`)\]]+",url)
                            if match.start() > 0)
                masked = masked[:start]+" "*(end-start)+masked[end:]
        url_text = decoded
        if urls:
            url_text = decoded_url(masked)
        urls.extend(re.findall(r"https?://[^\s<>\"'`)\]]+",url_text))
        for url in urls:
            try:
                reviewed_url(check,path,url,used)
            except Refused as error:
                raise Refused(f"{error}: {path}") from error
        for name,pattern in checks.items():
            for match in re.finditer(pattern,decoded,0 if name == "identifier" else re.I):
                value = match.group()
                if public_literal(path,decoded,match,name):
                    continue
                if name == "secret-hex" and value in known_hex:
                    continue
                accepted = [i for i,e in enumerate(exceptions)
                            if e["path"] == path and e["rule"] == name and e["value"] == value]
                require(accepted,f"{name}: {path}")
                used.update(accepted)
    check.used_exceptions = used
    check.report["scan_exceptions"] = [{k:v for k,v in e.items() if k != "value"} for e in exceptions]
    check.texts = texts


def historical_text(check):
    from review_rules import findings
    public_commits = [check.plan["public_base"]]
    if hasattr(check.args, "public_repo"):
        public_commits = git(check.args.public_repo, "rev-list", check.plan["public_base"]).decode().splitlines()
    slips = findings(check.texts, public_commits)
    require(not slips, "; ".join(f"{s['id']}: {s['path']}:{s['line']}" for s in slips))
    docs = claim_documents(check)
    patterns = {
        "0.0.1-R3": r"reads each session on the page once more to get them",
        "0.0.1-D1": r"(?:openwiz\s+ls|`ls`).{0,70}(?:every|all)\s+(?:thread|session)",
        "0.0.1-D2": r"--json.{0,70}(?:every|all)\s+command",
        "0.0.1-D3": r"\b(?:it|openwiz|reads?)\s+never\s+wakes?\b|never\s+(?:wakes|marks)\b[^.]{0,40}\bthread\s+read",
        "0.0.1-D4": r"works with (?:whatever|any|every|all).{0,40}room.cli",
        "0.0.3-R2": r"before you send,? it shows|that is said before you press|the effect is shown first",
    }
    exceptions = check.plan.get("scan_exceptions",[])
    for name,pattern in patterns.items():
        for path,text in docs.items():
            for match in re.finditer(pattern,text,re.I):
                accepted = [i for i,e in enumerate(exceptions)
                            if e["path"] == path and e["rule"] == "historical" and e["value"] == match.group()]
                require(accepted,f"{name}: unsupported historical wording in {path}")
                check.used_exceptions.update(accepted)
    require(check.used_exceptions == set(range(len(exceptions))),"unused scan exception")
    changelog = docs.get("CHANGELOG.md","")
    if "historical" not in check.plan:
        try:
            refuse_ranges(changelog)
        except Refused as error:
            raise Refused(f"0.0.1-R2: {error}") from error
    if "historical" in check.plan:
        approved = check.plan["historical"]
        try:
            heading, entry = changelog_entry(changelog,check.args.version)
        except Refused as error:
            raise Refused(f"0.0.1-R2: approved changelog entry: {error}") from error
        require(heading == approved["changelog_heading"] and sha(entry.encode()) == approved["entry_sha256"]
                and "PUBLICATION-DATE" not in changelog,
                "0.0.1-R2: approved changelog entry differs from the published entry")
    elif "entry" in check.plan:
        from entry import entries
        for item in entries(check.plan["entry"],check.args.version):
            expected = f'## {item["version"]} · {item["date"]}'
            require(changelog.splitlines().count(expected) == 1 and "PUBLICATION-DATE" not in changelog,
                    "0.0.1-R2: release needs exactly one approved dated entry")
    else:
        expected = f"## {check.args.version} · PUBLICATION-DATE"
        require(changelog.splitlines().count(expected) == 1 and changelog.count("PUBLICATION-DATE") == 1,
                "0.0.1-R2: release needs exactly one publication-date placeholder")
    count = sum(text.count("LIVE-PENDING") for text in check.texts.values())
    check.report["live_pending"] = count
    require(count == check.plan["live_pending"],"0.0.3-R6: declared placeholder count differs from the tree")
    check.report["publishable"] = count == 0


def claims(check):
    reviews = check.plan["claim_reviews"]
    require(isinstance(reviews,list),"claim reviews must be an array")
    docs = claim_documents(check)
    seen = set()
    declared = {}
    for document in check.plan.get("evidence_documents",[]):
        path = document["path"]
        require(path in docs and sha(check.texts[path].encode()) == document["sha256"],
                f"evidence document missing or stale: {path}")
        require(document["label"] in docs[path], f"evidence document label absent: {path}")
        declared[path] = document
    cited = set()
    for review in reviews:
        from check import shape, safe_path
        shape(review,"path sha256 claims")
        path = safe_path(review["path"])
        require(path in docs and path not in seen,"claim review path missing or repeated")
        seen.add(path)
        require(review["sha256"] == sha(check.texts[path].encode()),"claim review is stale")
        require(isinstance(review["claims"],list),"claim statements must be an array")
        covered = []
        for item in review["claims"]:
            shape(item,"text status evidence"+(" label" if "label" in item else ""))
            require(isinstance(item["text"],str) and item["text"] and item["text"] in docs[path],"claim text absent")
            status = item["status"]
            require(isinstance(status,str) and status in LABELS,"claim status unknown")
            require(isinstance(item["evidence"],str),"claim evidence must be a public relative link")
            if "label" in item:
                reviewed_label(path,item)
            if status != "context":
                if "label" not in item:
                    require(item["text"].lower().startswith(status+":"),"claim needs its public status label")
                require(item["evidence"],"claim evidence missing")
                evidence = link_target(check,"README.md",item["evidence"])
                require(evidence in docs,"claim evidence must be a public document")
                if status == "live-observation" and evidence in declared:
                    cited.add(evidence)
                elif status == "live-observation":
                    require("Live-observation:" in docs[evidence] and evidence.startswith("docs/evidence/"),
                            "0.0.1-R1: live capability needs published live evidence")
                if status == "live-observation":
                    require(not re.search(r"not published|unpublished|LIVE-PENDING",item["text"]),
                            "0.0.1-R1: live capability has unpublished evidence")
            covered.append(item["text"])
        fenced = False
        for line in docs[path].splitlines():
            if re.match(r"\s*(```|~~~)",line):
                fenced = not fenced
                continue
            if fenced or not line.strip() or re.match(r"#{1,6}(\s|$)",line):
                continue
            require(any(line in text for text in covered),f"claim ledger does not cover prose in {path}")
    require(seen == set(docs),"claim review missing for a document")
    require(set(declared) <= cited,"unused evidence document")


LABEL_FORMS = {"fixture-tested": ("fixture-tested", "fixture-test"),
               "live-observation": ("live-observation",),
               "source-inspection": ("source-inspection",),
               "unverified": ("unverified",), "proposal": ("proposal",)}


def reviewed_label(path, item):
    label = item["label"]
    require(item["status"] != "context", "context rows carry no label")
    require(isinstance(label,str) and label.strip() == label,
            "label must be the exact reviewed label text")
    if not label:
        return
    body = re.sub(r"^(?:\d+\.|[-*])\s+","",item["text"])
    require(body.startswith(label),"label must open its claim")
    form = re.sub(r"\s+","-",label.replace("*","").replace("_","").strip().lower())
    require(form.startswith(LABEL_FORMS[item["status"]]),"label does not name the claim's status")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        for key,value in attrs:
            if key in {"href","src"} and value:
                self.links.append(value)
            if key in {"id","name"} and value:
                self.ids.add(value)


def anchors(text):
    html = Links()
    html.feed(text)
    result = set(html.ids)
    counts = {}
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$",text,re.M):
        title = re.sub(r"\[([^\]]+)\]\([^)]*\)",r"\1",title)
        title = re.sub(r"<[^>]*>","",title)
        slug = re.sub(r"[^\w\- ]","",unescape(title).lower()).replace(" ","-")
        number = counts.get(slug,0)
        counts[slug] = number+1
        result.add(slug+(f"-{number}" if number else ""))
    for title in re.findall(r"^([^\n]+)\n(?:=+|-+)\s*$",text,re.M):
        result.add(re.sub(r"[^\w\- ]","",title.lower()).replace(" ","-"))
    return result


def link_target(check, source, url):
    parsed = urlsplit(unescape(url))
    require(not parsed.scheme and not parsed.netloc and not parsed.path.startswith("/"),"link: relative public evidence required")
    name = unquote(parsed.path)
    target = posixpath.normpath(posixpath.join(posixpath.dirname(source),name)) if name else source
    require(target != ".." and not target.startswith("../"),"link escapes public tree")
    files = {f["path"] for f in check.report["files"]}
    if target not in files:
        candidates = [target.rstrip("/")+"/README.md",target.rstrip("/")+"/index.html"]
        target = next((p for p in candidates if p in files),target)
    folder = target.rstrip("/")
    if target not in files and any(p.startswith(folder+"/") for p in files):
        require(not parsed.fragment,"link fragment missing")
        return folder
    require(target in files,"link target missing")
    if parsed.fragment:
        require(target in check.texts and unquote(parsed.fragment) in anchors(check.texts[target]),"link fragment missing")
    return target


def prose(text):
    kept, fence = [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"[ ]{0,3}(`{3,}|~{3,})",line)
        if marker and marker[1][0] == "`" and "`" in line.strip()[len(marker[1]):]:
            marker = None
        if fence is None and marker:
            fence, held = marker[1], [line]
        elif fence is not None:
            held.append(line)
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) \
                    and not line.strip()[len(marker[1]):].strip():
                fence = None
                kept.append("\n"*len(held))
        else:
            kept.append(line)
    return text if fence is not None else "".join(kept)


def markdown_links(text):
    refs,inline,destinations = {},[],[]
    for match in re.finditer(r"^\s*\[([^\]]+)\]:\s*<?([^\s>]+)>?",text,re.M):
        refs[match[1].lower()] = match[2]
        destinations.append((match[2],*match.span(2)))
    for match in re.finditer(r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+[\"'][^\n]*[\"'])?\s*\)",text):
        group = 1 if match[1] else 2
        inline.append(match[group])
        destinations.append((match[group],*match.span(group)))
    return refs,inline,destinations


def links(check):
    from repository import repository
    public_repo = repository(check.args.repo)
    for path,text in check.texts.items():
        if not path.endswith((".md",".html",".svg")):
            continue
        if path.endswith(".md"):
            text = prose(mask_records(text,record_spans(text,public_repo)))
        html = Links()
        html.feed(text)
        refs,inline,_ = markdown_links(text)
        urls = html.links+inline
        for label,key in re.findall(r"!?\[([^\]]+)\]\[([^\]]*)\]",text):
            require((key or label).lower() in refs,"link reference undefined")
            urls.append(refs[(key or label).lower()])
        urls.extend(refs.values())
        for url in urls:
            parsed = urlsplit(unescape(url))
            if parsed.scheme or parsed.netloc:
                reviewed_url(check,path,decoded_url(url))
            else:
                link_target(check,path,url)


REGRESSIONS = [
    ("0.0.3-R3","crates/adapters/cloudroom/src/process.rs", "tests/messaging/environment.rs",
     ["every_read_runs_without_the_thread_context","every_call_of_a_send_runs_without_the_thread_context"]),
]


RAW_STRING = re.compile(r'b?r(#*)"')
CHAR = re.compile(r"'(?:\\(?:x[0-9a-fA-F]{2}|u\{[0-9a-fA-F]{1,6}\}|.)|[^\\'\n])'")


def rust_code(text):
    blank = lambda part: re.sub(r"[^\n]"," ",part)
    out, i, n = [], 0, len(text)
    while i < n:
        word = i > 0 and (text[i-1].isalnum() or text[i-1] == "_")
        if text.startswith("//",i):
            j = text.find("\n",i)
            j = n if j < 0 else j
        elif text.startswith("/*",i):
            depth, j = 0, i
            while j < n:
                if text.startswith("/*",j):
                    depth, j = depth+1, j+2
                elif text.startswith("*/",j):
                    depth, j = depth-1, j+2
                    if not depth:
                        break
                else:
                    j += 1
            require(depth == 0,"unterminated Rust comment")
        elif not word and RAW_STRING.match(text,i):
            raw = RAW_STRING.match(text,i)
            j = text.find('"'+raw[1],raw.end())
            require(j >= 0,"unterminated Rust string")
            j += 1+len(raw[1])
        elif text[i] == '"' or (not word and text.startswith('b"',i)):
            j = i+(2 if text[i] == "b" else 1)
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            require(j < n,"unterminated Rust string")
            j += 1
        elif text[i] == "'" and CHAR.match(text,i):
            j = CHAR.match(text,i).end()
        else:
            out.append(text[i])
            i += 1
            continue
        out.append(blank(text[i:j]))
        i = j
    return "".join(out)


IDENT = re.compile(r"(?:r#)?[A-Za-z_][A-Za-z0-9_]*")
ITEM_KEYWORDS = {"mod", "use", "fn", "const", "static", "struct", "enum", "impl", "type", "trait"}
PAIRS = {"(": ")", "[": "]", "{": "}"}


def group_end(code, i):
    stack = []
    for j in range(i, len(code)):
        c = code[j]
        if c in PAIRS:
            stack.append(PAIRS[c])
        elif c in ")]}":
            require(stack and stack.pop() == c, "unbalanced Rust delimiters")
            if not stack:
                return j+1
    require(False, "unbalanced Rust delimiters")


def items(code):
    found, attrs, i, n = [], [], 0, len(code)

    def skip(k):
        while k < n and code[k].isspace():
            k += 1
        return k

    def word(k):
        m = IDENT.match(code, skip(k))
        require(m is not None, "unsupported top-level Rust form")
        return m.group(), m.end()

    while True:
        i = skip(i)
        if i >= n:
            break
        if code[i] == "#":
            j = skip(i+1+(code.startswith("#!", i)))
            require(j < n and code[j] == "[", "unsupported top-level Rust form")
            end = group_end(code, j)
            if not code.startswith("#!", i):
                attrs.append(" ".join(code[i:end].split()))
            i = end
            continue
        kw, j = word(i)
        require(not code.startswith("!", skip(j)), "item-level macro refused")
        if kw == "pub":
            k = skip(j)
            if k < n and code[k] == "(":
                j = group_end(code, k)
            kw, j = word(j)
        while True:
            require(not code.startswith("!", skip(j)), "item-level macro refused")
            if kw in ("unsafe", "async", "extern"):
                kw, j = word(j)
            elif kw == "const" and word(j)[0] in ("fn", "unsafe", "async", "extern"):
                kw, j = word(j)
            else:
                break
        require(kw in ITEM_KEYWORDS, "unsupported top-level Rust form")
        name = None
        if kw in ("mod", "fn", "struct", "enum", "trait", "type"):
            name, j = word(j)
        k = j
        form = body = None
        while True:
            k = skip(k)
            require(k < n, "unterminated top-level Rust item")
            c = code[k]
            if c == ";":
                form, k = ";", k+1
                break
            if c == "{":
                end = group_end(code, k)
                body, k = (k, end), end
                if kw in ("use", "const", "static", "type"):
                    continue
                form = "{"
                break
            if c in "([":
                k = group_end(code, k)
            elif c in ")]}":
                require(False, "unbalanced Rust delimiters")
            else:
                k += 1
        found.append({"kind": kw, "name": name, "attrs": attrs, "form": form, "body": body})
        attrs, i = [], k
    require(not attrs, "an attribute with no top-level item")
    return found


def file_module(main, module, paths, folder):
    found = [i for i in items(rust_code(main)) if i["kind"] == "mod" and i["name"] == module]
    require(len(found) == 1 and found[0]["form"] == ";","successor proof is not a module of its test target")
    require(not found[0]["attrs"],"successor module declaration carries an attribute (path override refused)")
    require(not any(p.startswith(folder+"/"+module+"/") for p in paths),"successor module path is ambiguous")


def real_tests(proof, tests):
    fns = [i for i in items(rust_code(proof)) if i["kind"] == "fn"]
    for test in tests:
        found = [i for i in fns if i["name"] == test]
        require(len(found) < 2,"named regression declared twice (cfg could choose which runs)")
        require(found and "#[test]" in found[0]["attrs"],"missing named regression (not a top-level #[test] fn)")


def test_body(proof, test):
    real_tests(proof, [test])
    found = [i for i in items(rust_code(proof)) if i["kind"] == "fn" and i["name"] == test]
    require(found[0]["form"] == "{","named regression has no body")
    return found[0]["body"]


def test_target(texts, target):
    try:
        import tomllib
    except ImportError:
        require(False,"regression successors need Python 3.11+ (tomllib reads the Cargo manifests)")

    def manifest(path):
        try:
            return tomllib.loads(texts[path])
        except tomllib.TOMLDecodeError:
            require(False,f"unreadable Cargo manifest {path}")

    def table(value):
        return value if isinstance(value,dict) else {}

    packages = [p for p in texts if PurePosixPath(p).name == "Cargo.toml"
                and table(manifest(p).get("package")).get("name") == "openwiz-tests"]
    require(len(packages) == 1,"test package is not exactly one exported manifest")
    folder = posixpath.dirname(packages[0])
    members = table(manifest("Cargo.toml").get("workspace")).get("members",[]) if "Cargo.toml" in texts else []
    require(folder and isinstance(members,list) and folder in members,"test package is not a listed workspace member")
    data = manifest(packages[0])
    require(data["package"].get("autotests") is False,"test targets are not explicit (autotests = false required)")
    entries = data.get("test",[])
    require(isinstance(entries,list) and all(isinstance(e,dict) for e in entries),"unsupported [[test]] table")
    found = [e for e in entries if e.get("name") == target]
    require(len(found) == 1 and set(found[0]) == {"name","path"} and isinstance(found[0]["path"],str),
            "successor test target is not one plain [[test]] entry")
    require(posixpath.normpath(posixpath.join(folder,found[0]["path"])) == f"tests/{target}/main.rs",
            "successor test target builds another file than its main.rs")


def regression_presence(check):
    check.regressions = []
    successors = {s["id"]:s for s in check.plan.get("regressions",[])}
    used = set()
    for name,feature,proof,tests in REGRESSIONS:
        if feature not in check.texts:
            continue
        if name == "0.0.3-R3" and tuple(map(int,check.args.version.split("."))) < (0,0,3):
            continue
        exact = None
        if name in successors:
            proof,tests = successors[name]["proof"],successors[name]["tests"]
            used.add(name)
            exact = []
        require(proof in check.texts,f"{name}: missing public regression proof")
        for test in tests:
            require(re.search(r"\bfn\s+"+re.escape(test)+r"\s*\(",check.texts[proof]),f"{name}: missing named regression")
        if exact is not None:
            folder,module = proof.rsplit("/",1)[0],PurePosixPath(proof).stem
            main = folder+"/main.rs"
            try:
                test_target(check.texts,folder.split("/")[1])
                if proof != main:
                    require(main in check.texts,"successor proof is not a module of its test target")
                    file_module(check.texts[main],module,check.texts,folder)
                real_tests(check.texts[proof],tests)
            except Refused as error:
                raise Refused(f"{name}: {error}") from error
            exact.extend(("" if proof == main else module+"::")+test for test in tests)
        check.regressions.append((name,proof,tests,exact))
    require(used == set(successors),"unused regression successor")
