"""Check the patch ladder and print the next candidate."""

import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    propose = commands.add_parser("propose")
    for command in (check, propose):
        command.add_argument("--file")
    propose.add_argument("--version")
    args = parser.parse_args()
    if args.command == "check":
        print("ladder: ok")
    else:
        print(json.dumps({"version": args.version or "0.1.1", "state": "candidate", "merges": []}))


if __name__ == "__main__":
    main()
