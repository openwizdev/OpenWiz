#!/usr/bin/env python3
import argparse
from datetime import datetime
from html import unescape
from pathlib import Path
import re
import sys
import tomllib
from urllib.parse import unquote, urlsplit


CHANNEL_HOSTS = {
    "tiktok": {"tiktok.com", "www.tiktok.com", "support.tiktok.com"},
    "youtube-shorts": {"youtube.com", "www.youtube.com", "youtu.be"},
    "show-hn": {"news.ycombinator.com"},
    "product-hunt": {"producthunt.com", "www.producthunt.com", "help.producthunt.com"},
    "github-trending": {"docs.github.com"},
    "reddit": {"reddit.com", "www.reddit.com", "old.reddit.com", "support.reddithelp.com"},
    "indie-hackers": {"indiehackers.com", "www.indiehackers.com"},
    "dev-to": {"dev.to"},
    "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "help.x.com"},
}
PROJECT_HOSTS = {"openwiz.dev", "www.openwiz.dev"}
STATUSES = {"draft", "approved", "posted"}
STRING_FIELDS = {"channel", "scheduled_pt", "title", "status", "posted_link"}
LIST_FIELDS = {"links", "media", "claims"}
OPTIONAL_FIELDS = {"tagline", "review_notes"}

ENGAGEMENT = {
    "star-trade": re.compile(
        r"\bstar[\s-]*for[\s-]*star\b|\b(?:trade|swap|exchange)\s+(?:github\s+)?stars\b"
        r"|\bstar\s+(?:yours|your (?:repo|project))[^.!?\n]*\bif[^.!?\n]*\bstar\b", re.I
    ),
    "upvote-request": re.compile(
        r"\bup[ -]?vote\s+(?:us|this|it|our|the)\b|\bvote\s+for\s+(?:us|our|this|the)\b"
        r"|\b(?:please|can you|could you|would you)\s+up[ -]?vote\b"
        r"|(?:^|[.!?\n:])\s*up[ -]?vote\b(?=\s|[.!?]|$)"
        r"|\b(?:give|drop|leave|send|need|want|asking for)\b[^.!?\n]{0,25}\bup[ -]?votes?\b"
        r"|\bup[ -]?votes?\s+(?:would|will)\s+help\b", re.I
    ),
    "star-request": re.compile(
        r"\bstar\s+(?:(?:us|openwiz|it)\b|(?:the|our|this)\s+(?:(?:github|openwiz)\s+)?"
        r"(?:repo(?:sitory)?|project)\b)|\b(?:please|can you|could you|would you)\s+star\b"
        r"|\b(?:give|drop|leave|send|need|want|asking for)\b[^.!?\n]{0,25}"
        r"(?:\b(?:github\s+)?stars?\b|[⭐🌟★])|\b(?:github\s+)?stars?\s+(?:would|will)\s+help\b", re.I
    ),
}
INLINE_LINK = re.compile(r"\]\(\s*<?([^\s<>)]+)|^ {0,3}\[[^\]\n]+\]:[ \t]*<?([^\s<>]+)", re.M)
URL_IN_COPY = re.compile(r"(?<![\w/:])(?:[a-z][a-z0-9+.-]*://|//|www\.)[^\s<>\"')\]`]+", re.I)
URI_PREFIX = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|www\.)", re.I)
BARE_DOMAIN = re.compile(
    r"(?<![\w./@:-])(?:[a-z0-9][a-z0-9-]*\.)+[a-z]{2,63}(?![\w-])"
    r"(?::[0-9]+)?(?:[/?#][^\s<>\"')\]`]+)?", re.I
)
MARKDOWN_CODE = re.compile(r"(`+).*?\1(?!`)", re.S)


def read_post(source):
    _, separator, rest = source.partition("\n")
    metadata, closing, body = rest.partition("\n+++\n")
    if not separator or not closing:
        raise ValueError("close the TOML header with +++ and add a Markdown body")
    try:
        fields = tomllib.loads(metadata)
    except tomllib.TOMLDecodeError:
        raise ValueError("the TOML header is invalid") from None
    required = STRING_FIELDS | LIST_FIELDS
    if fields.keys() - (required | OPTIONAL_FIELDS):
        raise ValueError("the TOML header contains an unknown field")
    for field in sorted(STRING_FIELDS | (OPTIONAL_FIELDS & fields.keys())):
        if not isinstance(fields.get(field), str):
            raise ValueError(f"{field} must be a quoted string")
    for field in sorted(LIST_FIELDS):
        items = fields.get(field)
        if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
            raise ValueError(f"{field} must be a list of nonempty strings")
    if fields["channel"] not in CHANNEL_HOSTS or fields["status"] not in STATUSES:
        raise ValueError("use a documented channel and status")
    if not fields["title"].strip() or not body.strip():
        raise ValueError("title and body must be nonempty")
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}", fields["scheduled_pt"]):
            raise ValueError
        datetime.strptime(fields["scheduled_pt"], "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError("scheduled_pt must be a valid PT date and time (YYYY-MM-DD HH:MM)") from None
    return fields, body


def allowed_url(url, channel):
    if re.search(r"[\s\\\x00-\x1f\x7f]", url):
        return False
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host:
            return False
    except ValueError:
        return False
    if host == "github.com":
        decoded_path = unquote(parsed.path).casefold()
        if "\\" in decoded_path or "%" in decoded_path:
            return False
        path = decoded_path.strip("/").split("/")
        return len(path) >= 2 and path[0] == "openwizdev" and not {"", ".", ".."}.intersection(path)
    return host in PROJECT_HOSTS or host in CHANNEL_HOSTS[channel]


def published_links(fields, copy):
    yield from fields["links"]
    yield from (item for item in fields["media"] if URI_PREFIX.match(item.strip()))
    if fields["posted_link"].strip():
        yield fields["posted_link"]
    for text in copy:
        text = unescape(text)
        yield from (inline or reference for inline, reference in INLINE_LINK.findall(text))
        yield from (url.rstrip(".,;!?") for url in URL_IN_COPY.findall(text))
        plain_text = MARKDOWN_CODE.sub(" ", URL_IN_COPY.sub(" ", text))
        yield from (f"https://{url.rstrip('.,;!?')}" for url in BARE_DOMAIN.findall(plain_text))


def normalize(text):
    return " ".join(text.split())


def contains_claim(claim, text):
    return bool(re.search(rf"(?<!\w){re.escape(claim)}(?!\w)", text))


def check_post(fields, body, changelog):
    channel, title = fields["channel"], fields["title"]
    tagline = fields.get("tagline", "")
    if channel == "show-hn" and not title.startswith("Show HN:"):
        yield "show-hn-title", "title must start with 'Show HN:'"
    if channel == "product-hunt" and (not tagline.strip() or len(tagline) > 60):
        yield "product-hunt-tagline", "provide a tagline of 1 to 60 characters"
    copy = (title, tagline, body)
    plain_copy = [re.sub(r"[*_`~]", "", unescape(text)) for text in copy]
    for rule, pattern in ENGAGEMENT.items():
        if any(pattern.search(text) for text in plain_copy):
            yield rule, "remove the engagement request or trade from the post copy"
    if any(not allowed_url(url, channel) for url in published_links(fields, copy)):
        yield "link-destination", "use full HTTP(S) URLs to OpenWiz or the post's own platform"
    claim_sources = [normalize(text) for text in copy]
    for index, text in enumerate(fields["claims"], start=1):
        claim = normalize(text)
        if not contains_claim(claim, changelog) or not any(contains_claim(claim, text) for text in claim_sources):
            yield "changelog-claim", f"claim {index} must appear verbatim in the copy and the given changelog"
    if fields["status"] == "posted" and not fields["posted_link"].strip():
        yield "posted-link", "a posted file needs its posted link"


def main():
    parser = argparse.ArgumentParser(description="Check local launch posts against their channel and release changelog.")
    parser.add_argument("folder", type=Path, help="folder containing Markdown launch posts")
    parser.add_argument("--changelog", required=True, type=Path, help="Markdown changelog for this release")
    args = parser.parse_args()
    try:
        changelog = normalize(args.changelog.read_text(encoding="utf-8"))
        if not changelog:
            raise ValueError
    except (OSError, ValueError):
        print(f"{args.changelog.name}: changelog-input: provide a readable, nonempty UTF-8 changelog", file=sys.stderr)
        return 1
    if not args.folder.is_dir():
        print(f"{args.folder.name}: post-folder: provide a folder", file=sys.stderr)
        return 1
    count, refused = 0, False
    for path in sorted(args.folder.rglob("*.md")):
        if path == args.changelog or not path.is_file():
            continue
        name = path.relative_to(args.folder).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            if source.partition("\n")[0] != "+++":
                continue
            count += 1
            fields, body = read_post(source)
            findings = list(check_post(fields, body, changelog))
        except (OSError, UnicodeError):
            findings = [("post-form", "provide readable UTF-8 Markdown")]
        except ValueError as error:
            findings = [("post-form", str(error))]
        for rule, message in findings:
            print(f"{name}: {rule}: {message}", file=sys.stderr)
        refused |= bool(findings)
    if not count and not refused:
        print(f"{args.folder.name}: post-folder: no post files found", file=sys.stderr)
        return 1
    if refused:
        return 1
    print(f"Checked {count} launch post(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
