import json
import math
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from openwiz_crm.errors import CrmError

API_NAME = re.compile(r"[a-z][a-z0-9_]{0,40}")
LABEL_MAX = 80
TEXT_MAX = 8000
ACTOR_MAX = 80
SEARCH_DEFAULT = 50
SEARCH_MAX = 200
CONTEXT_LINKS = 50
CONTEXT_CHANGES = 20
RESERVED_FIELDS = frozenset({"id", "object"})
FIELD_TYPES = frozenset({"text", "number", "boolean", "date", "select"})
DATE_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
PROVIDER = re.compile(r"[a-z][a-z0-9_-]{0,40}")
EXTERNAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,200}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    id INTEGER PRIMARY KEY,
    api_name TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('standard', 'custom')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fields (
    id INTEGER PRIMARY KEY,
    object_id INTEGER NOT NULL REFERENCES objects(id),
    api_name TEXT NOT NULL,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL,
    required INTEGER NOT NULL CHECK (required IN (0, 1)),
    options_json TEXT,
    origin TEXT NOT NULL CHECK (origin IN ('standard', 'custom')),
    UNIQUE (object_id, api_name)
);
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    object_id INTEGER NOT NULL REFERENCES objects(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS values_ (
    record_id TEXT NOT NULL REFERENCES records(id),
    field_id INTEGER NOT NULL REFERENCES fields(id),
    value_json TEXT NOT NULL,
    PRIMARY KEY (record_id, field_id)
);
CREATE TABLE IF NOT EXISTS associations (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL REFERENCES records(id),
    to_id TEXT NOT NULL REFERENCES records(id),
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (from_id, to_id, label)
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL,
    op TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS external_refs (
    provider TEXT NOT NULL,
    external_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    record_id TEXT NOT NULL REFERENCES records(id),
    PRIMARY KEY (provider, external_type, external_id)
);
CREATE INDEX IF NOT EXISTS records_object ON records(object_id);
CREATE INDEX IF NOT EXISTS values_field ON values_(field_id);
CREATE INDEX IF NOT EXISTS assoc_from ON associations(from_id);
CREATE INDEX IF NOT EXISTS assoc_to ON associations(to_id);
CREATE INDEX IF NOT EXISTS changes_record ON changes(record_id);
"""

STANDARD = (
    ("person", "Person", (
        ("name", "Name", "text", True, None),
        ("email", "Email", "text", False, None),
        ("role", "Role", "text", False, None),
    )),
    ("company", "Company", (
        ("name", "Name", "text", True, None),
        ("domain", "Domain", "text", False, None),
    )),
    ("deal", "Deal", (
        ("name", "Name", "text", True, None),
        ("stage", "Stage", "select", True,
         ["new", "qualifying", "proposal", "won", "lost"]),
        ("amount", "Amount", "number", False, None),
    )),
    ("activity", "Activity", (
        ("kind", "Kind", "select", True,
         ["note", "email", "meeting", "call", "slack", "github", "x", "other"]),
        ("summary", "Summary", "text", True, None),
        ("body", "Body", "text", False, None),
        ("happened_at", "Happened at", "date", False, None),
        ("source", "Source", "text", False, None),
    )),
)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix):
    return prefix + secrets.token_hex(8)


def _api_name(value, label):
    if not isinstance(value, str) or API_NAME.fullmatch(value) is None:
        raise CrmError("validation", label + " must be a lowercase api name")
    if value in RESERVED_FIELDS:
        raise CrmError("validation", label + " is reserved")
    return value


def _label(value):
    if not isinstance(value, str):
        raise CrmError("validation", "label must be text")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > LABEL_MAX or any(ord(c) < 32 for c in cleaned):
        raise CrmError("validation", "label must be 1 to 80 visible characters")
    return cleaned


def _external(provider, external_type, external_id):
    if not isinstance(provider, str) or PROVIDER.fullmatch(provider) is None:
        raise CrmError("validation", "provider must be a lowercase name")
    if not isinstance(external_type, str) or EXTERNAL_ID.fullmatch(external_type) is None:
        raise CrmError("validation", "external type has an unsupported shape")
    if not isinstance(external_id, str) or EXTERNAL_ID.fullmatch(external_id) is None:
        raise CrmError("validation", "external id has an unsupported shape")
    return provider, external_type, external_id


def _revision(value):
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CrmError("validation", "if_revision must be the record's revision")


def _expect_revision(row, if_revision):
    if if_revision is not None and row["revision"] != if_revision:
        raise CrmError("conflict", "record changed since it was read")


def _actor(value):
    if not isinstance(value, str) or not value.strip() or len(value) > ACTOR_MAX:
        raise CrmError("validation", "actor must be 1 to 80 characters")
    if any(ord(c) < 32 for c in value):
        raise CrmError("validation", "actor must not contain control characters")
    return value


def _options(value):
    if not isinstance(value, list) or not value or len(value) > 50:
        raise CrmError("validation", "select needs 1 to 50 options")
    seen = []
    for item in value:
        if not isinstance(item, str) or API_NAME.fullmatch(item) is None or item in seen:
            raise CrmError("validation", "each option must be a unique api name")
        seen.append(item)
    return seen


def normalize(field, value):
    kind = field["field_type"]
    if kind == "text":
        if not isinstance(value, str) or not value or len(value) > TEXT_MAX:
            raise CrmError("validation", field["api_name"] + " must be text of 1 to 8000 characters")
        if any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise CrmError("validation", field["api_name"] + " contains a control character")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise CrmError("validation", field["api_name"] + " must be a number")
        if isinstance(value, str):
            try:
                number = float(value) if "." in value else int(value)
            except ValueError:
                raise CrmError("validation", field["api_name"] + " must be a number") from None
        else:
            number = value
        if isinstance(number, float) and not math.isfinite(number):
            raise CrmError("validation", field["api_name"] + " must be a finite number")
        if isinstance(number, float) and number.is_integer():
            number = int(number)
        if abs(number) >= 10 ** 15:
            raise CrmError("validation", field["api_name"] + " is out of range")
        return number
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise CrmError("validation", field["api_name"] + " must be true or false")
    if kind == "date":
        if not isinstance(value, str):
            raise CrmError("validation", field["api_name"] + " must be a date")
        try:
            if DATE_DAY.fullmatch(value):
                datetime.strptime(value, "%Y-%m-%d")
            elif DATE_TIME.fullmatch(value):
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            else:
                raise ValueError
        except ValueError:
            raise CrmError(
                "validation",
                field["api_name"] + " must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ",
            ) from None
        return value
    if kind == "select":
        options = json.loads(field["options_json"])
        if not isinstance(value, str) or value not in options:
            raise CrmError(
                "validation",
                field["api_name"] + " must be one of: " + ", ".join(options),
            )
        return value
    raise CrmError("validation", "unknown field type")


class Store:
    def __init__(self, connection):
        self._conn = connection

    @classmethod
    def open(cls, path):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(target)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        store = cls(connection)
        store._seed()
        return store

    def close(self):
        self._conn.close()

    def _seed(self):
        with self._conn:
            count = self._conn.execute("SELECT COUNT(*) AS n FROM objects").fetchone()["n"]
            if count:
                return
            stamp = now()
            for api_name, label, fields in STANDARD:
                cursor = self._conn.execute(
                    "INSERT INTO objects (api_name, label, kind, created_at) VALUES (?, ?, 'standard', ?)",
                    (api_name, label, stamp),
                )
                object_id = cursor.lastrowid
                for name, field_label, field_type, required, options in fields:
                    self._conn.execute(
                        """INSERT INTO fields
                           (object_id, api_name, label, field_type, required, options_json, origin)
                           VALUES (?, ?, ?, ?, ?, ?, 'standard')""",
                        (object_id, name, field_label, field_type, int(required),
                         None if options is None else json.dumps(options)),
                    )

    def schema(self):
        objects = []
        rows = self._conn.execute(
            "SELECT * FROM objects ORDER BY id"
        ).fetchall()
        for row in rows:
            fields = self._conn.execute(
                "SELECT * FROM fields WHERE object_id = ? ORDER BY id", (row["id"],)
            ).fetchall()
            objects.append({
                "api_name": row["api_name"],
                "label": row["label"],
                "kind": row["kind"],
                "fields": [self._field_public(field) for field in fields],
            })
        return {"objects": objects}

    def add_object(self, api_name, label):
        api_name = _api_name(api_name, "object name")
        label = _label(label)
        with self._conn:
            if self._object(api_name, required=False) is not None:
                raise CrmError("conflict", "object already exists")
            self._conn.execute(
                "INSERT INTO objects (api_name, label, kind, created_at) VALUES (?, ?, 'custom', ?)",
                (api_name, label, now()),
            )
        return {"api_name": api_name, "label": label, "kind": "custom", "fields": []}

    def add_field(self, object_name, api_name, label, field_type, required=False, options=None):
        api_name = _api_name(api_name, "field name")
        label = _label(label if label is not None else api_name)
        if field_type not in FIELD_TYPES:
            raise CrmError("validation", "type must be text, number, boolean, date or select")
        if not isinstance(required, bool):
            raise CrmError("validation", "required must be true or false")
        if field_type == "select":
            options = _options(options)
        elif options not in (None, []):
            raise CrmError("validation", "options are only for select fields")
        else:
            options = None
        with self._conn:
            obj = self._object(object_name)
            existing = self._conn.execute(
                "SELECT id FROM fields WHERE object_id = ? AND api_name = ?",
                (obj["id"], api_name),
            ).fetchone()
            if existing is not None:
                raise CrmError("conflict", "field already exists")
            if required:
                count = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM records WHERE object_id = ?",
                    (obj["id"],),
                ).fetchone()["n"]
                if count:
                    raise CrmError(
                        "validation",
                        "cannot add a required field when records already exist",
                    )
            self._conn.execute(
                """INSERT INTO fields
                   (object_id, api_name, label, field_type, required, options_json, origin)
                   VALUES (?, ?, ?, ?, ?, ?, 'custom')""",
                (obj["id"], api_name, label, field_type, int(required),
                 None if options is None else json.dumps(options)),
            )
        return {
            "object": object_name,
            "api_name": api_name,
            "label": label,
            "type": field_type,
            "required": required,
            "options": options,
            "origin": "custom",
        }

    def create_record(self, object_name, fields, actor):
        actor = _actor(actor)
        with self._conn:
            return self._insert_record(object_name, fields, actor)

    def update_record(self, object_name, record_id, fields, clear, actor, if_revision=None):
        actor = _actor(actor)
        _revision(if_revision)
        if not isinstance(fields, dict) or not isinstance(clear, list):
            raise CrmError("validation", "fields must be an object and clear must be a list")
        if not fields and not clear:
            raise CrmError("validation", "nothing to change")
        overlap = set(fields).intersection(clear)
        if overlap:
            raise CrmError("validation", "cannot set and clear the same field")
        with self._conn:
            obj = self._object(object_name)
            row = self._live(record_id)
            if row["object_id"] != obj["id"]:
                raise CrmError("object_mismatch", "record is not a " + object_name)
            _expect_revision(row, if_revision)
            known = self._fields(obj["id"])
            self._known_names(known, list(fields) + list(clear))
            current = self._values(record_id)
            changes = []
            for name in clear:
                field = known[name]
                if field["required"]:
                    raise CrmError("validation", name + " is required")
                if name not in current:
                    continue
                self._conn.execute(
                    "DELETE FROM values_ WHERE record_id = ? AND field_id = ?",
                    (record_id, field["id"]),
                )
                changes.append({"field": name, "before": current[name], "after": None})
            for name, raw in fields.items():
                field = known[name]
                value = normalize(field, raw)
                if current.get(name) == value:
                    continue
                self._conn.execute(
                    """INSERT INTO values_ (record_id, field_id, value_json) VALUES (?, ?, ?)
                       ON CONFLICT (record_id, field_id) DO UPDATE SET value_json = excluded.value_json""",
                    (record_id, field["id"], json.dumps(value)),
                )
                changes.append({"field": name, "before": current.get(name), "after": value})
            if not changes:
                return self._public_record(record_id)
            stamp = now()
            self._touch(record_id, stamp)
            self._change(record_id, "update", {"fields": changes}, actor, stamp)
            return self._public_record(record_id)

    def get_record(self, record_id):
        self._record_row(record_id)
        return self._public_record(record_id)

    def delete_record(self, object_name, record_id, actor, if_revision=None):
        actor = _actor(actor)
        _revision(if_revision)
        with self._conn:
            obj = self._object(object_name)
            row = self._live(record_id)
            if row["object_id"] != obj["id"]:
                raise CrmError("object_mismatch", "record is not a " + object_name)
            _expect_revision(row, if_revision)
            stamp = now()
            self._conn.execute(
                """UPDATE records
                   SET deleted_at = ?, updated_at = ?, revision = revision + 1
                   WHERE id = ?""",
                (stamp, stamp, record_id),
            )
            self._change(record_id, "delete", {}, actor, stamp)
            return self._public_record(record_id)

    def search(self, object_name, query=None, where=None, limit=SEARCH_DEFAULT):
        if where is None:
            where = {}
        if not isinstance(where, dict):
            raise CrmError("validation", "where must be an object")
        if query is not None and (not isinstance(query, str) or not query.strip()):
            raise CrmError("validation", "query must be non-empty text")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= SEARCH_MAX:
            raise CrmError("validation", "limit must be an integer from 1 to 200")
        obj = self._object(object_name)
        known = self._fields(obj["id"])
        self._known_names(known, list(where))
        wanted = {name: normalize(known[name], raw) for name, raw in where.items()}
        needle = query.casefold() if query else None
        rows = self._conn.execute(
            """SELECT id FROM records
               WHERE object_id = ? AND deleted_at IS NULL
               ORDER BY updated_at DESC, id DESC""",
            (obj["id"],),
        ).fetchall()
        matched = []
        for row in rows:
            values = self._values(row["id"])
            if any(values.get(name) != wanted[name] for name in wanted):
                continue
            if needle is not None:
                haystack = "\n".join(
                    str(values[name]) for name, field in known.items()
                    if field["field_type"] in ("text", "select") and name in values
                ).casefold()
                if needle not in haystack:
                    continue
            matched.append(self._public_record(row["id"]))
            if len(matched) > limit:
                break
        truncated = len(matched) > limit
        return {"records": matched[:limit], "truncated": truncated}

    def associate(self, from_id, to_id, label, actor):
        actor = _actor(actor)
        label = _api_name(label, "association label")
        with self._conn:
            self._live(from_id)
            self._live(to_id)
            existing = self._conn.execute(
                "SELECT id FROM associations WHERE from_id = ? AND to_id = ? AND label = ?",
                (from_id, to_id, label),
            ).fetchone()
            if existing is not None:
                raise CrmError("conflict", "association already exists")
            stamp = now()
            assoc_id = new_id("rel_")
            self._conn.execute(
                "INSERT INTO associations (id, from_id, to_id, label, created_at) VALUES (?, ?, ?, ?, ?)",
                (assoc_id, from_id, to_id, label, stamp),
            )
            detail = {"id": assoc_id, "from_id": from_id, "to_id": to_id, "label": label}
            self._touch(from_id, stamp)
            self._touch(to_id, stamp)
            self._change(from_id, "associate", detail, actor, stamp)
            self._change(to_id, "associate", detail, actor, stamp)
            return detail | {"created_at": stamp}

    def log_activity(self, kind, summary, links, actor, body=None, happened_at=None, source="agent"):
        actor = _actor(actor)
        if not isinstance(links, list) or not links:
            raise CrmError("validation", "an activity needs at least one linked record")
        if len(set(links)) != len(links):
            raise CrmError("validation", "activity links must be unique")
        if not all(isinstance(item, str) for item in links):
            raise CrmError("validation", "activity links must be record ids")
        fields = {
            "kind": kind,
            "summary": summary,
            "happened_at": happened_at or now(),
            "source": source,
        }
        if body is not None:
            fields["body"] = body
        with self._conn:
            for link in links:
                self._live(link)
            record = self._insert_record("activity", fields, actor)
            created = []
            stamp = now()
            for link in links:
                assoc_id = new_id("rel_")
                self._conn.execute(
                    "INSERT INTO associations (id, from_id, to_id, label, created_at) VALUES (?, ?, ?, 'about', ?)",
                    (assoc_id, record["id"], link, stamp),
                )
                detail = {"id": assoc_id, "from_id": record["id"], "to_id": link, "label": "about"}
                self._change(record["id"], "associate", detail, actor, stamp)
                self._change(link, "associate", detail, actor, stamp)
                self._touch(link, stamp)
                created.append(detail | {"created_at": stamp})
            return {"record": self._public_record(record["id"]), "links": created}

    def context(self, record_id):
        self._record_row(record_id)
        links = self._conn.execute(
            """SELECT * FROM associations
               WHERE from_id = ? OR to_id = ?
               ORDER BY created_at DESC, id DESC""",
            (record_id, record_id),
        ).fetchall()
        published = []
        for link in links[:CONTEXT_LINKS]:
            other = link["to_id"] if link["from_id"] == record_id else link["from_id"]
            direction = "out" if link["from_id"] == record_id else "in"
            published.append({
                "id": link["id"],
                "label": link["label"],
                "direction": direction,
                "created_at": link["created_at"],
                "record": self._public_record(other),
            })
        changes = self._conn.execute(
            """SELECT id, op, detail_json, actor, at FROM changes
               WHERE record_id = ? ORDER BY id DESC LIMIT ?""",
            (record_id, CONTEXT_CHANGES),
        ).fetchall()
        return {
            "record": self._public_record(record_id),
            "links": published,
            "changes": [
                {
                    "id": change["id"],
                    "op": change["op"],
                    "detail": json.loads(change["detail_json"]),
                    "actor": change["actor"],
                    "at": change["at"],
                }
                for change in changes
            ],
            "truncated": len(links) > CONTEXT_LINKS,
        }

    def bind_ref(self, provider, external_type, external_id, record_id):
        provider, external_type, external_id = _external(provider, external_type, external_id)
        with self._conn:
            self._live(record_id)
            current = self._conn.execute(
                """SELECT record_id FROM external_refs
                   WHERE provider = ? AND external_type = ? AND external_id = ?""",
                (provider, external_type, external_id),
            ).fetchone()
            if current is not None and current["record_id"] != record_id:
                raise CrmError("conflict", "external id is already bound")
            if current is None:
                self._conn.execute(
                    """INSERT INTO external_refs
                       (provider, external_type, external_id, record_id) VALUES (?, ?, ?, ?)""",
                    (provider, external_type, external_id, record_id),
                )
        return {
            "provider": provider,
            "external_type": external_type,
            "external_id": external_id,
            "id": record_id,
        }

    def find_ref(self, provider, external_type, external_id):
        provider, external_type, external_id = _external(provider, external_type, external_id)
        row = self._conn.execute(
            """SELECT record_id FROM external_refs
               WHERE provider = ? AND external_type = ? AND external_id = ?""",
            (provider, external_type, external_id),
        ).fetchone()
        if row is None:
            raise CrmError("not_found", "external id is not bound")
        return self._public_record(row["record_id"])

    def _insert_record(self, object_name, fields, actor):
        if not isinstance(fields, dict):
            raise CrmError("validation", "fields must be an object")
        obj = self._object(object_name)
        known = self._fields(obj["id"])
        self._known_names(known, list(fields))
        missing = [
            name for name, field in known.items() if field["required"] and name not in fields
        ]
        if missing:
            raise CrmError("validation", "missing required field: " + ", ".join(missing))
        normalized = {name: normalize(known[name], raw) for name, raw in fields.items()}
        stamp = now()
        record_id = new_id("rec_")
        self._conn.execute(
            "INSERT INTO records (id, object_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (record_id, obj["id"], stamp, stamp),
        )
        for name, value in normalized.items():
            self._conn.execute(
                "INSERT INTO values_ (record_id, field_id, value_json) VALUES (?, ?, ?)",
                (record_id, known[name]["id"], json.dumps(value)),
            )
        self._change(record_id, "create", {"fields": normalized}, actor, stamp)
        return self._public_record(record_id)

    def _object(self, api_name, required=True):
        if not isinstance(api_name, str):
            raise CrmError("validation", "object must be a name")
        row = self._conn.execute(
            "SELECT * FROM objects WHERE api_name = ?", (api_name,)
        ).fetchone()
        if row is None and required:
            raise CrmError("unknown_object", "unknown object: " + api_name)
        return row

    def _fields(self, object_id):
        rows = self._conn.execute(
            "SELECT * FROM fields WHERE object_id = ? ORDER BY id", (object_id,)
        ).fetchall()
        return {row["api_name"]: row for row in rows}

    def _known_names(self, known, names):
        unknown = [name for name in names if name not in known]
        if unknown:
            raise CrmError("unknown_field", "unknown field: " + ", ".join(unknown))

    def _record_row(self, record_id):
        if not isinstance(record_id, str) or not record_id.startswith("rec_"):
            raise CrmError("not_found", "record not found")
        row = self._conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise CrmError("not_found", "record not found")
        return row

    def _live(self, record_id):
        row = self._record_row(record_id)
        if row["deleted_at"] is not None:
            raise CrmError("not_found", "record is deleted")
        return row

    def _values(self, record_id):
        rows = self._conn.execute(
            """SELECT fields.api_name AS name, values_.value_json AS value_json
               FROM values_ JOIN fields ON fields.id = values_.field_id
               WHERE values_.record_id = ?""",
            (record_id,),
        ).fetchall()
        return {row["name"]: json.loads(row["value_json"]) for row in rows}

    def _public_record(self, record_id):
        row = self._record_row(record_id)
        obj = self._conn.execute(
            "SELECT api_name FROM objects WHERE id = ?", (row["object_id"],)
        ).fetchone()
        return {
            "id": row["id"],
            "object": obj["api_name"],
            "fields": self._values(record_id),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
            "revision": row["revision"],
        }

    def _touch(self, record_id, stamp):
        self._conn.execute(
            "UPDATE records SET updated_at = ?, revision = revision + 1 WHERE id = ?",
            (stamp, record_id),
        )

    def _change(self, record_id, op, detail, actor, stamp):
        self._conn.execute(
            "INSERT INTO changes (record_id, op, detail_json, actor, at) VALUES (?, ?, ?, ?, ?)",
            (record_id, op, json.dumps(detail, sort_keys=True), actor, stamp),
        )

    def _field_public(self, field):
        return {
            "api_name": field["api_name"],
            "label": field["label"],
            "type": field["field_type"],
            "required": bool(field["required"]),
            "options": None if field["options_json"] is None else json.loads(field["options_json"]),
            "origin": field["origin"],
        }
