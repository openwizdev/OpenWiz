import argparse
import json
import os
import sqlite3
import sys

from openwiz_crm.errors import CrmError
from openwiz_crm.store import Store


def emit(payload):
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")


def fail(error):
    emit(error.payload())
    return 1


def pairs(values):
    fields = {}
    for item in values or []:
        if "=" not in item:
            raise CrmError("validation", "expected name=value")
        name, raw = item.split("=", 1)
        if not name or name in fields:
            raise CrmError("validation", "each field may be set once")
        fields[name] = raw
    return fields


def build_parser():
    parser = argparse.ArgumentParser(
        prog="crm.py",
        description="Local CRM for agents. Prints one JSON object to stdout.",
    )
    parser.add_argument("--db", default=os.environ.get("OPENWIZ_CRM_DB"))
    parser.add_argument("--actor", default="agent")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Create the database and standard objects")
    commands.add_parser("schema", help="List objects and fields")

    object_add = commands.add_parser("object-add", help="Add a custom object")
    object_add.add_argument("--name", required=True)
    object_add.add_argument("--label", required=True)

    field_add = commands.add_parser("field-add", help="Add a custom field")
    field_add.add_argument("--object", required=True)
    field_add.add_argument("--name", required=True)
    field_add.add_argument("--label")
    field_add.add_argument("--type", required=True, dest="field_type")
    field_add.add_argument("--required", action="store_true")
    field_add.add_argument("--option", action="append", dest="options")

    create = commands.add_parser("record-create", help="Create a record")
    create.add_argument("--object", required=True)
    create.add_argument("--set", action="append", dest="sets")

    get = commands.add_parser("record-get", help="Get one record, including a deleted one")
    get.add_argument("--id", required=True)

    update = commands.add_parser("record-update", help="Change fields on a record")
    update.add_argument("--object", required=True)
    update.add_argument("--id", required=True)
    update.add_argument("--set", action="append", dest="sets")
    update.add_argument("--clear", action="append", dest="clear")
    update.add_argument("--if-revision", type=int)

    delete = commands.add_parser("record-delete", help="Soft-delete a record")
    delete.add_argument("--object", required=True)
    delete.add_argument("--id", required=True)
    delete.add_argument("--if-revision", type=int)

    search = commands.add_parser("record-search", help="Search live records")
    search.add_argument("--object", required=True)
    search.add_argument("--query")
    search.add_argument("--where", action="append", dest="wheres")
    search.add_argument("--limit", type=int, default=50)

    associate = commands.add_parser("associate", help="Link two records")
    associate.add_argument("--from", dest="from_id", required=True)
    associate.add_argument("--to", required=True)
    associate.add_argument("--label", required=True)

    activity = commands.add_parser("activity-log", help="Record an activity and link it")
    activity.add_argument("--kind", required=True)
    activity.add_argument("--summary", required=True)
    activity.add_argument("--body")
    activity.add_argument("--happened-at")
    activity.add_argument("--source", default="cli")
    activity.add_argument("--link", action="append", dest="links", required=True)

    context = commands.add_parser("context", help="Record, one hop of links, and recent changes")
    context.add_argument("--id", required=True)

    bind = commands.add_parser("ref-bind", help="Bind an external id to a record")
    bind.add_argument("--provider", required=True)
    bind.add_argument("--type", required=True)
    bind.add_argument("--external-id", required=True)
    bind.add_argument("--id", required=True)

    find = commands.add_parser("ref-get", help="Find a record by external id")
    find.add_argument("--provider", required=True)
    find.add_argument("--type", required=True)
    find.add_argument("--external-id", required=True)
    return parser


def run(args):
    if not args.db:
        raise CrmError("validation", "pass --db or set OPENWIZ_CRM_DB")
    store = Store.open(args.db)
    try:
        if args.command == "init":
            result = store.schema()
        elif args.command == "schema":
            result = store.schema()
        elif args.command == "object-add":
            result = store.add_object(args.name, args.label)
        elif args.command == "field-add":
            result = store.add_field(
                args.object, args.name, args.label, args.field_type,
                args.required, args.options,
            )
        elif args.command == "record-create":
            result = store.create_record(args.object, pairs(args.sets), args.actor)
        elif args.command == "record-get":
            result = store.get_record(args.id)
        elif args.command == "record-update":
            result = store.update_record(
                args.object, args.id, pairs(args.sets), args.clear or [], args.actor,
                args.if_revision,
            )
        elif args.command == "record-delete":
            result = store.delete_record(args.object, args.id, args.actor, args.if_revision)
        elif args.command == "record-search":
            result = store.search(args.object, args.query, pairs(args.wheres), args.limit)
        elif args.command == "associate":
            result = store.associate(args.from_id, args.to, args.label, args.actor)
        elif args.command == "activity-log":
            result = store.log_activity(
                args.kind, args.summary, args.links, args.actor,
                args.body, args.happened_at, args.source,
            )
        elif args.command == "context":
            result = store.context(args.id)
        elif args.command == "ref-bind":
            result = store.bind_ref(args.provider, args.type, args.external_id, args.id)
        elif args.command == "ref-get":
            result = store.find_ref(args.provider, args.type, args.external_id)
        else:
            raise CrmError("validation", "unknown command")
    finally:
        store.close()
    return result


def main(argv=None):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        emit({"ok": True, "result": run(args)})
        return 0
    except CrmError as error:
        return fail(error)
    except sqlite3.Error:
        return fail(CrmError("internal", "database error"))
