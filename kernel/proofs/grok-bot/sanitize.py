"""Stub: copies every record through unchanged (the red run)."""
import json, sys
raw = json.load(open(sys.argv[2]))
out = [f"#{i['number']} {i['title']}\n{i['body']}\n" + ''.join(c['body'] + '\n' for c in i['comments']) for i in raw['items']]
open(sys.argv[4], 'w').write('\n'.join(out))
print('stages: ok')
