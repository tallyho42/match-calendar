#!/usr/bin/env python3
"""Prune old fixtures, apply date/time changes, re-sort month sections, bump the stamp.

Usage: update.py updates.json [--file PATH] [--dry-run]

updates.json:
{
  "prune_days": 10,                       # optional, default 10 (matches page's display window)
  "updates": [
    {"teams": "Arsenal – Brentford", "date": "2027-01-06",   # teams text + CURRENT data-date day
     "new": "2027-01-05T20:30:00"},                          # new local (Czech) datetime
    {"teams": "Real Madrid – Celta", "date": "2026-11-22", "tba": true}   # time unknown again
  ]
}
"""
import re, sys, json, datetime

args = sys.argv[1:]
dry = '--dry-run' in args
path = '/Users/premek/Code/Match Calendar/index.html'
if '--file' in args:
    path = args[args.index('--file') + 1]
cfg_path = [a for a in args if not a.startswith('--') and a != path][0]
cfg = json.load(open(cfg_path, encoding='utf-8'))

DAYS = ['Po', 'Út', 'St', 'Čt', 'Pá', 'So', 'Ne']
MONTHS = {1: 'Leden', 2: 'Únor', 3: 'Březen', 4: 'Duben', 5: 'Květen', 6: 'Červen', 7: 'Červenec',
          8: 'Srpen', 9: 'Září', 10: 'Říjen', 11: 'Listopad', 12: 'Prosinec'}

now = datetime.datetime.now()
cutoff = (now - datetime.timedelta(days=cfg.get('prune_days', 10))).strftime('%Y-%m-%d') + 'T00:00:00'

d = open(path, encoding='utf-8').read()
head = '<main class="schedule" id="scheduleRoot">\n'
start = d.index(head) + len(head)
end = d.index('    <div class="empty-state" id="emptyState"')
arts = re.findall(r'      <article class="match-card.*?\n      </article>\n', d[start:end], flags=re.S)


def setdt(a, iso, tba=False):
    dt = datetime.datetime.fromisoformat(iso)
    day = DAYS[dt.weekday()]
    shown = '--:--' if tba else dt.strftime('%H:%M')
    when = '%s %s · %s' % (day, dt.strftime('%d.%m.%Y'), 'čas TBA' if tba else shown)
    a = re.sub(r'data-date="[^"]+"', 'data-date="%s"' % iso, a, 1)
    a = re.sub(r'data-when="[^"]+"', 'data-when="%s"' % when, a, 1)
    a = re.sub(r'<span class="mc-day">[^<]*</span>', '<span class="mc-day">%s</span>' % day, a, 1)
    a = re.sub(r'<span class="mc-date">[^<]*</span>', '<span class="mc-date">%s</span>' % dt.strftime('%d.%m'), a, 1)
    a = re.sub(r'<span class="mc-time">[^<]*</span>', '<span class="mc-time">%s</span>' % shown, a, 1)
    return a


upd = {(u['teams'], u['date']): u for u in cfg.get('updates', [])}
used, kept, removed = set(), [], []
for i, a in enumerate(arts):
    date = re.search(r'data-date="([^"]+)"', a).group(1)
    teams = re.search(r'data-teams="([^"]+)"', a).group(1)
    if date < cutoff:
        removed.append((date, teams)); continue
    key = (teams, date[:10])
    if key in upd:
        u = upd[key]
        if u.get('tba'):
            date = date[:10] + 'T00:00:00'
            a = setdt(a, date, tba=True)
        else:
            date = u['new']
            a = setdt(a, date)
        used.add(key)
    kept.append((date, i, a))

missing = set(upd) - used
if missing:
    sys.exit('NO MATCH for updates (check teams text / old date; removed matches cannot be updated): %s' % sorted(missing))

kept.sort(key=lambda t: (t[0], t[1]))
groups = {}
for date, i, a in kept:
    groups.setdefault(date[:7], []).append(a)
out = ''
for ym in sorted(groups):
    y, m = ym.split('-')
    out += '    <section class="month-group" data-month="%s">\n      <div class="month-header"><span>%s %s</span></div>\n' % (ym, MONTHS[int(m)], y)
    out += ''.join(groups[ym]) + '    </section>\n'
d = d[:start] + out + d[end:]

stamp = now.strftime('%Y-%m-%dT%H:%M:00')
d = re.sub(r'data-updated="[^"]+"', 'data-updated="%s"' % stamp, d, 1)
d = re.sub(r'<span>Aktualizováno [^<]*</span>',
           '<span>Aktualizováno %s · %s</span>' % (now.strftime('%d.%m.%Y'), now.strftime('%H:%M')), d, 1)

assert d.count('<article') == d.count('</article>') == len(kept)
assert d.count('<section') == d.count('</section>')

print('cutoff %s: removed %d, kept %d, updates applied %d' % (cutoff[:10], len(removed), len(kept), len(used)))
for r in removed: print('  removed', r[0][:10], r[1])
horizon = (now + datetime.timedelta(days=14)).strftime('%Y-%m-%dT%H:%M:%S')
stale = [a for dt_, i, a in kept if now.strftime('%Y-%m-%dT%H:%M:%S') <= dt_ <= horizon and 'čas TBA' in a]
print('TBA within 14 days (banner will warn): %d' % len(stale))
for a in stale: print('  ', re.search(r'data-when="([^"]+)"', a).group(1), re.search(r'data-teams="([^"]+)"', a).group(1))
if dry:
    print('dry-run: file not written')
else:
    open(path, 'w', encoding='utf-8').write(d)
    print('written', path)
