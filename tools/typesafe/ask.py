#!/usr/bin/env python3
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import client


def main():
    if client.from_env() is None:
        return 1
    try:
        req = json.load(sys.stdin)
        questions = req['questions']
        if not isinstance(questions, dict) or not questions:
            return 1
        resp = client.from_env().system_one(req['state'], questions, req.get('model') or client.MODEL)
        json.dump(resp, sys.stdout)
        sys.stdout.write('\n')
        return 0
    except Exception:
        return 1


if __name__ == '__main__':
    sys.exit(main())
