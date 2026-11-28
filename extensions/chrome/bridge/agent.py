import re
import urllib.parse

SCHEMA = "openwiz.chrome.v1"
MAX_TEXT = 16 * 1024
MAX_URL = 2048
MAX_TITLE = 300
MAX_SELECTION = 4000
MAX_PAGE_TEXT = 20000
MAX_REPLY = 8000
MAX_ACTIONS = 3

STOP = {
    "this", "that", "page", "what", "whats", "about", "does", "with", "from", "have",
    "your", "you", "the", "and", "for", "are", "was", "how", "why", "when", "where",
    "which", "who", "whom", "whose", "into", "onto", "over", "under", "after", "before",
    "please", "tell", "show", "read", "open", "looking", "there", "here", "just",
    "something", "anything", "summarize", "summary", "title", "address", "link",
    "selection", "selected", "highlighted", "text", "content", "words", "says", "say",
    "does", "will", "can", "could", "would", "should", "them", "they", "their",
}

NAV = re.compile(r"^(please\s+)?(open|go to|goto|navigate to|visit)\b", re.I)
CLICK = re.compile(r"^(please\s+)?(click|press|tap)\b", re.I)
TYPE = re.compile(r"^(please\s+)?(type|enter|fill)\b", re.I)
READ = re.compile(r"^(please\s+)?read\b", re.I)
URL = re.compile(r"https?://[^\s<>'\"]+")
LABELED = re.compile(r"(?:labeled|called|named)\s+(.+)$", re.I)
SELECTOR = re.compile(r"(#[A-Za-z][\w:-]*|\.[A-Za-z][\w:-]*|\[[^\]]+\])")
WORD = re.compile(r"[A-Za-z0-9']{4,}")


def clip(value, limit):
    if not isinstance(value, str):
        return ""
    return value.replace("\0", "")[:limit]


def normalize_page(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        return False
    return {
        "url": clip(value.get("url", ""), MAX_URL),
        "title": clip(value.get("title", ""), MAX_TITLE),
        "selection": clip(value.get("selection", ""), MAX_SELECTION),
        "text": clip(value.get("text", ""), MAX_PAGE_TEXT),
    }


def allowed_http(url):
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    if not parts.hostname or parts.username or parts.password:
        return False
    return True


def sanitize_action(raw, ident):
    if not isinstance(raw, dict):
        return None
    op = raw.get("op")
    if op not in ("read", "click", "type", "navigate"):
        return None
    action = {
        "id": clip(str(ident), 64),
        "op": op,
        "description": clip(raw.get("description", ""), 200),
        "selector": clip(raw.get("selector", ""), 300),
        "text": clip(raw.get("text", ""), 200),
        "url": clip(raw.get("url", ""), MAX_URL),
        "value": clip(raw.get("value", ""), 2000),
    }
    if any(mark in action["selector"] for mark in ("\n", "\r", "<", ">")):
        return None
    if op == "navigate" and not allowed_http(action["url"]):
        return None
    if op == "click" and not action["selector"] and not action["text"]:
        return None
    if op == "type" and not action["value"]:
        return None
    if op == "read" and (action["url"] or action["value"]):
        return None
    if not action["description"]:
        action["description"] = {
            "read": "Read this tab",
            "click": "Click in this tab",
            "type": "Type in this tab",
            "navigate": "Open a link in this tab",
        }[op]
    return action


def sanitize_actions(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    kept = []
    for index, item in enumerate(raw, 1):
        action = sanitize_action(item, item.get("id") if isinstance(item, dict) else "")
        if action is None:
            continue
        action["id"] = clip(action["id"] or f"a{index}", 64) or f"a{index}"
        kept.append(action)
        if len(kept) == MAX_ACTIONS:
            break
    return kept


def first_url(message):
    found = URL.search(message)
    if not found:
        return ""
    return found.group(0).rstrip(".,);]")


def click_fields(message):
    labeled = LABELED.search(message.strip())
    if labeled:
        return clip(labeled.group(1).strip().strip("\"'"), 200), ""
    quoted = re.search(r'"([^"]+)"', message)
    if quoted:
        return clip(quoted.group(1).strip(), 200), ""
    selector = SELECTOR.search(message)
    if selector and " " not in selector.group(1):
        return "", clip(selector.group(1), 300)
    match = re.search(
        r"^(?:please\s+)?(?:click|press|tap)\s+(?:on\s+)?(?:the\s+)?(.+)$",
        message.strip(),
        re.I,
    )
    if not match:
        return "", ""
    target = re.sub(r"\s+(button|link|tab|field)\.?$", "", match.group(1).strip(), flags=re.I)
    return clip(target.strip(), 200), ""


def type_fields(message):
    selector = ""
    found = re.search(r"(?:into|in)\s+(#[^\s]+|\.[^\s]+|\[[^\]]+\])", message, re.I)
    if found:
        selector = clip(found.group(1), 300)
    quoted = re.search(r'"([^"]*)"', message)
    if quoted:
        return clip(quoted.group(1), 2000), selector
    match = re.search(r"^(?:please\s+)?(?:type|enter|fill)\s+(.+)$", message.strip(), re.I)
    if not match:
        return "", selector
    rest = re.split(r"\s+(?:into|in)\s+", match.group(1).strip(), maxsplit=1)[0]
    return clip(rest.strip().strip("\"'"), 2000), selector


def mentions(word, sentence):
    if word in sentence:
        return True
    stem = word[:-1] if word.endswith("s") and len(word) > 4 else ""
    return bool(stem) and stem in sentence


def sentence_about(question, text):
    words = [word.lower() for word in WORD.findall(question) if word.lower() not in STOP]
    if not words or not text:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]
    hits = [part for part in parts if any(mentions(word, part.lower()) for word in words)]
    if not hits:
        return ""
    hits.sort(key=len)
    return hits[0][:500]


def proposal(op, description, **fields):
    raw = {"op": op, "description": description, "selector": "", "text": "", "url": "", "value": ""}
    raw.update(fields)
    action = sanitize_action(raw, "a1")
    return [] if action is None else [action]


def answer(text, page):
    message = text.strip()
    folded = message.lower()
    if NAV.match(message):
        url = first_url(message)
        if not url or not allowed_http(url):
            return "I can open an http or https address in this tab after you grant it.", []
        return (
            "I can open that address in this tab after you grant it.",
            proposal("navigate", f"Open {url[:160]}", url=url),
        )
    if CLICK.match(message):
        label, selector = click_fields(message)
        if not label and not selector:
            return "Tell me what to click, then grant this tab.", []
        shown = label or selector
        return (
            f"I can click {shown} after you grant this tab.",
            proposal("click", f"Click {shown[:160]}", text=label, selector=selector),
        )
    if TYPE.match(message):
        value, selector = type_fields(message)
        if not value:
            return "Tell me what to type, then grant this tab.", []
        return (
            "I can type into this tab after you grant it.",
            proposal("type", "Type into this tab", value=value, selector=selector),
        )
    if READ.match(message) and (page is None or "again" in folded):
        if page is None:
            return (
                "I can read this tab after you grant it.",
                proposal("read", "Read this tab"),
            )
        return (
            "I can read this tab again after you grant it.",
            proposal("read", "Read this tab again"),
        )
    if page is None:
        if any(word in folded for word in ("title", "url", "address", "selection", "page", "summar")):
            return "No page was attached. Turn on Include this page, then ask again.", []
        return (
            "I am the local page agent. Ask about the page you attach, or tell me to click, type or open a link.",
            [],
        )
    title = page["title"].strip() or "Untitled page"
    if "title" in folded:
        if page["title"].strip():
            return f"The title is {page['title'].strip()}.", []
        return "This page has no title.", []
    if any(word in folded for word in ("url", "address", "link")):
        if page["url"]:
            return f"The address is {page['url']}.", []
        return "This page has no address.", []
    if "select" in folded or "highlight" in folded:
        if page["selection"].strip():
            return f"The selection is: {page['selection'].strip()}", []
        return "Nothing is selected on this page.", []
    found = sentence_about(message, page["text"])
    if found:
        return f"On {title}: {found}", []
    if any(word in folded for word in ("page", "summar", "looking", "about")):
        excerpt = page["text"].strip()
        if len(excerpt) > 480:
            excerpt = excerpt[:480].rstrip() + "…"
        if excerpt:
            return f"{title} ({page['url']}). {excerpt}", []
        return f"{title} ({page['url']}). The page has no readable text.", []
    return (
        f"I have {title} ({page['url']}). Ask about the title, the address, the selection or the words on the page.",
        [],
    )
