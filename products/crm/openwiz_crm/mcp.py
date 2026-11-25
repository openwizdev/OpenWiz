import json
import os
import sqlite3
import sys

from openwiz_crm import __version__
from openwiz_crm.errors import CrmError
from openwiz_crm.store import Store

PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
SERVER_NAME = "openwiz-crm"

TOOLS = (
    {
        "name": "crm_schema",
        "description": "List CRM objects and their fields, including custom ones.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "crm_object_add",
        "description": "Add a custom object. Standard objects are person, company, deal and activity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "label": {"type": "string"},
            },
            "required": ["name", "label"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crm_field_add",
        "description": "Add a custom field to an object. type is text, number, boolean, date or select.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object": {"type": "string"},
                "name": {"type": "string"},
                "label": {"type": "string"},
                "type": {"type": "string"},
                "required": {"type": "boolean"},
                "options": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["object", "name", "type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crm_record_create",
        "description": "Create a record. fields uses the object's api names.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object": {"type": "string"},
                "fields": {"type": "object"},
                "actor": {"type": "string"},
            },
            "required": ["object", "fields"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crm_record_update",
        "description": "Update a live record. clear removes optional fields. Pass if_revision from a prior read to refuse a stale write.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object": {"type": "string"},
                "id": {"type": "string"},
                "fields": {"type": "object"},
                "clear": {"type": "array", "items": {"type": "string"}},
                "actor": {"type": "string"},
                "if_revision": {"type": "integer"},
            },
            "required": ["object", "id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crm_record_search",
        "description": "Search live records of one object. query matches text and select fields. where is exact.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object": {"type": "string"},
                "query": {"type": "string"},
                "where": {"type": "object"},
                "limit": {"type": "integer"},
            },
            "required": ["object"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crm_record_context",
        "description": "Return one record, one hop of linked records, and recent changes.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crm_associate",
        "description": "Create a labeled association from one record to another.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_id": {"type": "string"},
                "to_id": {"type": "string"},
                "label": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["from_id", "to_id", "label"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crm_activity_log",
        "description": "Log an activity and link it to one or more records with the label about.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "summary": {"type": "string"},
                "body": {"type": "string"},
                "happened_at": {"type": "string"},
                "source": {"type": "string"},
                "links": {"type": "array", "items": {"type": "string"}},
                "actor": {"type": "string"},
            },
            "required": ["kind", "summary", "links"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crm_ref_bind",
        "description": "Bind a provider, object type and external id to a live record. The type is required because some CRMs reuse ids across objects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "external_type": {"type": "string"},
                "external_id": {"type": "string"},
                "id": {"type": "string"},
            },
            "required": ["provider", "external_type", "external_id", "id"],
            "additionalProperties": False,
        },
    },
)


def _object(value):
    if not isinstance(value, dict):
        raise CrmError("validation", "arguments must be an object")
    return value


def _call(store, name, arguments):
    args = _object(arguments or {})
    actor = args.get("actor", "mcp")
    if name == "crm_schema":
        _only(args, set())
        return store.schema()
    if name == "crm_object_add":
        _only(args, {"name", "label"})
        _need(args, "name", "label")
        return store.add_object(args["name"], args["label"])
    if name == "crm_field_add":
        _only(args, {"object", "name", "label", "type", "required", "options"})
        _need(args, "object", "name", "type")
        return store.add_field(
            args["object"], args["name"], args.get("label"), args["type"],
            args.get("required", False), args.get("options"),
        )
    if name == "crm_record_create":
        _only(args, {"object", "fields", "actor"})
        _need(args, "object", "fields")
        return store.create_record(args["object"], args["fields"], actor)
    if name == "crm_record_update":
        _only(args, {"object", "id", "fields", "clear", "actor", "if_revision"})
        _need(args, "object", "id")
        return store.update_record(
            args["object"], args["id"], args.get("fields", {}), args.get("clear", []), actor,
            args.get("if_revision"),
        )
    if name == "crm_record_search":
        _only(args, {"object", "query", "where", "limit"})
        _need(args, "object")
        return store.search(
            args["object"], args.get("query"), args.get("where"), args.get("limit", 50),
        )
    if name == "crm_record_context":
        _only(args, {"id"})
        _need(args, "id")
        return store.context(args["id"])
    if name == "crm_associate":
        _only(args, {"from_id", "to_id", "label", "actor"})
        _need(args, "from_id", "to_id", "label")
        return store.associate(args["from_id"], args["to_id"], args["label"], actor)
    if name == "crm_activity_log":
        _only(args, {"kind", "summary", "body", "happened_at", "source", "links", "actor"})
        _need(args, "kind", "summary", "links")
        return store.log_activity(
            args["kind"], args["summary"], args["links"], actor,
            args.get("body"), args.get("happened_at"), args.get("source", "mcp"),
        )
    if name == "crm_ref_bind":
        _only(args, {"provider", "external_type", "external_id", "id"})
        _need(args, "provider", "external_type", "external_id", "id")
        return store.bind_ref(
            args["provider"], args["external_type"], args["external_id"], args["id"],
        )
    raise CrmError("unknown_tool", "unknown tool: " + str(name))


def _only(args, allowed):
    extra = set(args) - allowed
    if extra:
        raise CrmError("validation", "unexpected argument: " + ", ".join(sorted(extra)))


def _need(args, *keys):
    missing = [key for key in keys if key not in args]
    if missing:
        raise CrmError("validation", "missing argument: " + ", ".join(missing))


def _required(name, args, keys):
    missing = [key for key in keys if key not in args]
    if missing:
        raise CrmError("validation", name + " missing " + ", ".join(missing))


def dispatch(store, message):
    if not isinstance(message, dict):
        return _rpc_error(None, -32600, "invalid request")
    method = message.get("method")
    has_id = "id" in message
    msg_id = message.get("id")
    if not isinstance(method, str):
        if not has_id:
            return None
        return _rpc_error(msg_id, -32600, "invalid request")
    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None
    if not has_id:
        return None
    if method == "initialize":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": list(TOOLS)}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        try:
            _required("tools/call", params, ["name"])
            result = _call(store, params.get("name"), params.get("arguments") or {})
            text = json.dumps({"ok": True, "result": result}, sort_keys=True)
            is_error = False
        except CrmError as error:
            text = json.dumps(error.payload(), sort_keys=True)
            is_error = True
        except sqlite3.Error:
            text = json.dumps(CrmError("internal", "database error").payload(), sort_keys=True)
            is_error = True
        except Exception:
            text = json.dumps(CrmError("internal", "tool failed").payload(), sort_keys=True)
            is_error = True
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
        }
    return _rpc_error(msg_id, -32601, "method not found")


def _rpc_error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(store, stdin, stdout):
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = _rpc_error(None, -32700, "parse error")
        else:
            response = dispatch(store, message)
        if response is not None:
            stdout.write(json.dumps(response, sort_keys=True) + "\n")
            stdout.flush()


def main():
    path = os.environ.get("OPENWIZ_CRM_DB")
    if not path:
        sys.stderr.write("openwiz-crm: set OPENWIZ_CRM_DB\n")
        return 2
    try:
        store = Store.open(path)
    except sqlite3.Error:
        sys.stderr.write("openwiz-crm: database error\n")
        return 1
    try:
        serve(store, sys.stdin, sys.stdout)
    finally:
        store.close()
    return 0
