import json, sys
sys.path.insert(0, '.')
import numpy as np
from sectorloom_agent.ibt import read_ibt_file

s = read_ibt_file(sys.argv[1], {'file': 'synthetic.ibt', 'date': '2026-10-01T19:30:00'})
pick = [0, 250, 500, 750, 999]
r6 = lambda v: None if v is None else round(float(v), 6)
r4 = lambda v: round(float(v), 4)
gsum = lambda a: round(float(np.sum(a.astype(np.float64))), 4)

def grid(g):
    if g is None: return None
    out = {k: [r4(g[k][i]) for i in pick] for k in ('t','spd','thr','brk','gear')}
    out['longg'] = [r4(g['longg'][i]) for i in pick] if 'longg' in g else None
    out['slip'] = [round(float(g['slip'][i]), 5) for i in pick] if 'slip' in g else None
    out['slipa'] = [r4(g['slipa'][i]) for i in pick] if 'slipa' in g else None
    out['yawr'] = [round(float(g['yawr'][i]), 5) for i in pick] if 'yawr' in g else None
    out['abs'] = gsum(g['abs']) if 'abs' in g else None
    out['slipsum'] = gsum(g['slip']) if 'slip' in g else None
    out['x'] = [round(float(g['x'][i]), 2) for i in pick] if 'x' in g else None
    out['tsum'] = gsum(g['t']); out['spdsum'] = gsum(g['spd'])
    return out

print(json.dumps({
 'track': s['track'], 'car': s['car'], 'driver': s['driver'],
 'sessionType': s['sessionType'], 'trackKey': s['trackKey'], 'bestId': s['bestId'],
 'cond': {k: (float(v) if isinstance(v,(int,float)) and not isinstance(v,bool) else v)
          for k,v in s['cond'].items()},
 'laps': [{'num': l['num'], 'time': r6(l['time']), 'pit': l['pit'], 'off': l['off'],
           'complete': l['complete'], 'clean': l['clean'], 'stint': l['stint'], 'best': l['best'],
           'fuel': r6(l.get('fuel')),
           'sec': ([None if v is None else round(float(v), 5) for v in l['sec']] if l.get('sec') else None),
           'g': grid(l.get('g'))} for l in s['laps']],
 'stints': [{'no': st['no'], 'firstLap': st['firstLap'], 'lastLap': st['lastLap'],
             'total': st['total'], 'cleanN': st['cleanN'], 'best': r6(st['best']),
             'avg': r6(st['avg']), 'sd': r6(st['sd']), 'fuel': r6(st['fuel'])} for st in s['stints']],
 'fuelMax': r6(s.get('fuelMax')),
 'sectors': s.get('sectors'), 'entry': s.get('entry'), 'sub': s.get('sub'), 'aids': s.get('aids'),
 'tyres': ({'n': len(s['tyres']), 'first': s['tyres'][0], 'last': s['tyres'][-1]} if s.get('tyres') else None),
 'map': ({'n': len(s['map']['x']), 'x0': s['map']['x'][0], 'y0': s['map']['y'][0],
          'x50': s['map']['x'][50]} if s['map'] else None),
 'setupKeys': list((s['setup'] or {}).keys())
}, indent=1, default=float))
