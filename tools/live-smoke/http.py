#!/usr/bin/env python3
import http.client
import json
import sys

try:
    port, path = int(sys.argv[1]), sys.argv[2]
    if not 1 <= port <= 65535 or not path.startswith('/api/v1/') or any(c in path for c in '\r\n?#'):
        raise ValueError()
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=45)
    try:
        connection.request('GET', path, headers={'Connection': 'close'})
        response = connection.getresponse()
        raw = response.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError()
        body = raw.decode('utf-8')
        if response.status != 200:
            raise ValueError()
        sys.stdout.write(body)
    finally:
        connection.close()
except (ValueError, OSError, http.client.HTTPException, IndexError):
    print(json.dumps({'unavailable': True}))
    raise SystemExit(3)
