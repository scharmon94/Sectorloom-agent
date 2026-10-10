import json, sys, math
import os
OUT = os.environ.get('TMPDIR', '/tmp')
a = json.load(open(os.path.join(OUT, 'js.json')))
b = json.load(open(os.path.join(OUT, 'py.json')))
TOL = 2e-3          # float32 round-trip and 64-vs-32-bit accumulation
diffs = []

def walk(x, y, path=''):
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)):
            if k not in x: diffs.append(f'{path}.{k}: missing in browser')
            elif k not in y: diffs.append(f'{path}.{k}: missing in python')
            else: walk(x[k], y[k], f'{path}.{k}')
    elif isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y):
            diffs.append(f'{path}: length {len(x)} vs {len(y)}'); return
        for i, (p, q) in enumerate(zip(x, y)): walk(p, q, f'{path}[{i}]')
    elif isinstance(x, bool) or isinstance(y, bool):
        if bool(x) != bool(y): diffs.append(f'{path}: {x} vs {y}')
    elif isinstance(x, (int, float)) and isinstance(y, (int, float)):
        if x == 0 and y == 0: return
        scale = max(abs(x), abs(y), 1e-9)
        if abs(x - y) / scale > TOL and abs(x - y) > TOL:
            diffs.append(f'{path}: {x} vs {y}')
    else:
        if x != y: diffs.append(f'{path}: {x!r} vs {y!r}')

walk(a, b)
if diffs:
    print(f'{len(diffs)} DIFFERENCE(S):'); [print('  -', d) for d in diffs[:40]]; sys.exit(1)
print('PARITY OK — browser and agent produce the same session')
print('  laps:', len(a['laps']), '| complete:', sum(1 for l in a['laps'] if l['complete']),
      '| clean:', sum(1 for l in a['laps'] if l['clean']), '| stints:', len(a['stints']))
print('  lap times:', [l['time'] for l in a['laps']])
