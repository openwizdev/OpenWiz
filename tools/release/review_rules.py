import re

STATE_DOCS = {'README.md', 'CHANGELOG.md', 'RELEASING.md', 'docs/testing.md'}
HASH_DOCS = {'README.md', 'docs/testing.md'}
PRIVATE_POINTERS = (
    "ticket 0.0.3-1's evidence", "source-diagnostics fix's evidence README",
    "ticket 1's real baseline", 'contracts/fleet.v1.md', 'docs/design-rules.md',
)


def comment_spans(path, text):
    if not path.endswith(('.rs', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.css', '.sh', '.py')):
        return
    if path.endswith(('.sh', '.py')):
        quote = None
        heredoc = None
        offset = 0
        for line in text.splitlines(keepends=True):
            if heredoc:
                if line.strip() == heredoc: heredoc = None
                offset += len(line)
                continue
            pending = None
            i = 0
            while i < len(line):
                ch = line[i]
                if quote:
                    if ch == '\\' and quote != "'": i += 2; continue
                    if line.startswith(quote, i): i += len(quote); quote = None; continue
                elif ch in "\"'":
                    quote = ch
                elif ch == '\\': i += 2; continue
                elif ch == '#' and (i == 0 or line[i-1].isspace()):
                    yield offset+i, offset+len(line.rstrip('\r\n'))
                    break
                elif path.endswith('.sh') and line.startswith('<<', i):
                    match = re.match(r'''<<-?\s*(['"]?)([A-Za-z_][A-Za-z_0-9]*)\1''', line[i:])
                    if match: pending = match[2]
                i += 1
            heredoc = pending
            offset += len(line)
        return
    rust = path.endswith('.rs')
    i, n = 0, len(text)
    while i < n:
        if rust and text[i] == 'r':
            raw = re.match(r'r(#+)?"', text[i:])
            if raw:
                end = text.find('"'+(raw[1] or ''), i+len(raw[0]))
                if end != -1: i = end+1+len(raw[1] or ''); continue
        if text.startswith('//', i):
            end = text.find('\n', i)
            end = n if end == -1 else end
            yield i, end
            i = end
        elif text.startswith('/*', i):
            start, depth = i, 1
            i += 2
            while i < n and depth:
                if rust and text.startswith('/*', i): depth += 1; i += 2
                elif text.startswith('*/', i): depth -= 1; i += 2
                else: i += 1
            yield start, i
        elif text[i] in ('"', "'", '`') and (not rust or text[i] == '"' or re.match(r"'(?:\\.|[^'\\\n])'", text[i:])):
            quote = text[i]
            i += 1
            while i < n:
                if text[i] == '\\': i += 2
                elif text[i] == quote: i += 1; break
                else: i += 1
        else:
            i += 1


REVIEW_HISTORY = re.compile(r'\b(?:correction|review)[-\s]+rounds?\b|\bfinding(?:s)?\s+(?:ids?\b|#?[A-Z]{0,3}-?\d+\b)|\breview(?:er)?\s+[:#]?\s*[A-Z]{1,3}-?\d+\b', re.I)
EVIDENCE_POINTER = re.compile(r"\b(?:in|see|under|from|refer to|links? to)\s+(?:(?:the|our)\s+)?(?:(?:private|internal)\s+)?evidence\b|\bevidence\s+(?:README|notes?|records?|reports?|directory|folder)\b|\b(?:private|internal)/[\w.-]+|\b(?:private|internal)\s+(?:notes?|evidence|records?|reports?|docs?|readme|procedures?)\b|\bticket\s+\d+(?:\.\d+)*(?:['’]s)?\s+(?:procedure|evidence|record|notes|baseline)\b", re.I)
COMMENT_PUNCTUATION = re.compile(r'(?<=\S)[ \t]+(?:[,:;]|\.(?![.\w]))|^[ \t]*[,.:;](?:[ \t]|$)')
GLUED_EXTENSION = re.compile(r'\b(?:a|an|the|not|or|and|named|called|with|as|into|to|is|in|for|of|use|using|ends?|ending|extension|suffix)\.(?:[cm]?[jt]sx?|rs|py|sh|css|html|json|ya?ml|md|svg|png|jpe?g|gif|webp|avif|heic|heif|txt|pdf)\b', re.I)


def comment_findings(path, text):
    previous = (0, '')
    for start, end in comment_spans(path, text):
        number = text.count('\n', 0, start)+1
        for index, line in enumerate(text[start:end].split('\n')):
            prose = re.sub(r'^\s*(?://[/!]?|/\*[*!]?|\*|#)\s?', '', line)
            semantic = prose
            prose = re.sub(r'`[^`]*`', 'CODE', prose)
            context = previous[1]+' '+semantic if previous[0] == number+index-1 else semantic
            previous = (number+index, semantic)
            for rule, pattern in [('review-history', REVIEW_HISTORY), ('evidence-pointer', EVIDENCE_POINTER),
                                  ('comment-punctuation', COMMENT_PUNCTUATION), ('glued-extension', GLUED_EXTENSION)]:
                if pattern.search(context if rule in {'review-history', 'evidence-pointer'} else prose):
                    yield {'id': '0.0.5-L4', 'rule': rule, 'path': path, 'line': number+index}


def findings(texts, public_commits=()):
    out = []
    for path, text in sorted(texts.items()):
        out.extend(comment_findings(path, text))
        for number, line in enumerate(text.split('\n'), 1):
            if path.endswith('.md') and re.search(r'\([ \t]*[;,:]', line):
                out.append({'id': '0.0.5-L4', 'rule': 'prose-punctuation', 'path': path, 'line': number})
            if path in STATE_DOCS and re.search(
                r'\bstaged\b|\bapproval pending\b|\bawait(?:s|ing)?(?: that)? approval\b|publication still requires',
                line, re.I):
                out.append({'id': '0.0.5-M1', 'path': path, 'line': number})
            if path == 'docs/testing.md' and re.search(
                r'exact-head independent export review|commit email|maintainer approval of files', line, re.I):
                out.append({'id': '0.0.5-M1', 'path': path, 'line': number})
            if path in HASH_DOCS:
                for match in re.finditer(r'\b[0-9a-f]{7,40}\b', line, re.I):
                    if not any(commit.startswith(match[0].lower()) for commit in public_commits):
                        out.append({'id': '0.0.5-M2', 'path': path, 'line': number})
            if path in STATE_DOCS and re.search(r"this head['’]s actual command results|private export record (?:holds|binds)", line, re.I):
                out.append({'id': '0.0.5-L1', 'path': path, 'line': number})
            if path in {'CHANGELOG.md', 'RELEASING.md', 'docs/dependencies.md'} and 'setup' in line.lower() and re.search(r'\]\((?:docs/)?web-access\.md\)', line):
                out.append({'id': '0.0.5-L2', 'path': path, 'line': number})
            if path == 'docs/dependencies.md' and (('v127 tested' in line and 'historical' not in line.lower()) or 'No Safari test is recorded' in line):
                out.append({'id': '0.0.5-L3', 'path': path, 'line': number})
            placeholder = re.search(r"\(the check\b|(?:^|[:(,]|//+|\*)\s*the check\)|,\s*the check\s*[),]|sheet['’]s\s+the check|approval sheet|\bsheet[ \t]+[,):]|\bsheet[ \t]+$|\bsheet(?:,)?\s+the check\b|the check(?:,| to | and |, unchanged by |, as )the check|the the check|the implementation the check", line, re.I)
            if placeholder or any(pointer in line for pointer in PRIVATE_POINTERS):
                out.append({'id': '0.0.5-L4', 'path': path, 'line': number})
    return out
