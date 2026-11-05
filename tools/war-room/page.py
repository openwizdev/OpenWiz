#!/usr/bin/env python3
"""A separate private local page, rendered solely from one saved suite record."""
from html import escape
import json

import suite
from sources import safe_record

TITLES = ('Throughput by direction', 'Stage waits, limits and ticket misses',
          'Board and bench readiness', 'CI running / queued per pool and cost today',
          'Credits and Claude usage', 'Pending decisions')
NAMES = {'activity': 'Current activity', 'stage_waits': 'Stage waits',
         'board': 'Board', 'ci_bench': 'CI bench', 'factory_metrics': 'Daily factory',
         'journey': 'Ticket journeys', 'skills_eval': 'Skills eval',
         'cost': 'All-in cost per merged PR', 'credits': 'Credits',
         'claude_usage': 'Claude usage', 'decisions': 'Pending decisions',
         'answer_time': 'Orchestrator answer time', 'rework': 'Rework rate',
         'eb6': 'EB6', 'eb7': 'EB7', 'eb8': 'EB8', 'eb9': 'EB9'}


def esc(value):
    return escape(str(value), quote=True)


def metric_html(metric):
    m = metric
    value = 'Unknown' if m['value'] is None else f"{m['value']} {m['unit']}"
    window = m['window']
    span = 'Window unavailable' if window is None else f"[{window['since']}, {window['until']}) {window['timezone']}"
    source = m['source']
    provenance = 'Source unavailable' if source is None else f"{source['path']} · {source['schema']} · SHA-256 {source['sha256']}"
    bound = 'unknown validity bound' if m['fresh_until'] is None else 'fresh through ' + m['fresh_until']
    dimensions = ' · '.join(k + ': ' + str(v) for k, v in m['dimensions'].items() if v is not None)
    links = ' '.join(f'<a href="{esc(url)}" rel="noreferrer noopener">source {i}</a>'
                     for i, url in enumerate(m['evidence'], 1))
    # Each detail row names its kind, so a drawn picture can keep the rows that tell one value
    # from another (window, freshness, statistic, dimensions) and leave out the rest (#2565).
    details = [('window', span), ('observed', f"Observed {m['observed_at'] or 'Unknown'} · {m['freshness']} · {bound}"),
               ('statistic', f"{m['statistic']} · native unit {m['native_unit']} · "
                f"coverage {m['sample']['observed']}/{m['sample']['expected'] if m['sample']['expected'] is not None else 'Unknown'}"),
               ('dimensions', dimensions), ('source', provenance)]
    if m['interval'] is not None:
        details.append(('interval', 'Interval ' + json.dumps(m['interval'], sort_keys=True)))
    details.extend(('prerequisite', p) for p in m['prerequisites'])
    return (f'<article class="metric {esc(m["state"])} {esc(m["freshness"])}">'
            f'<h4>{esc(m["label"])}</h4><strong>{esc(value)}</strong> '
            f'<span class="badge">{esc(m["state"])}</span>'
            + ''.join(f'<p class="detail {kind}">{esc(d)}</p>' for kind, d in details if d)
            + f'<p class="links">{links}</p></article>')


def render(record):
    safe_record(record)
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             '<meta http-equiv="refresh" content="300"><title>Private War room</title>',
             '<style>body{margin:0;background:#101722;color:#e8edf4;font:16px/1.5 system-ui,sans-serif}'
             'main{max-width:1120px;margin:auto;padding:32px}header{border-bottom:1px solid #465569;padding-bottom:20px}'
             'h1{font-size:36px;margin:0}h2{font-size:23px;margin-top:36px}h3{font-size:18px}h4{margin:0 0 8px}'
             'a{color:#a7d5ff}article,.provider{border:1px solid #465569;border-radius:10px;padding:16px;margin:12px 0}'
             '.metric{background:#182538}.metric strong{font-size:26px}.detail{font-size:13px;overflow-wrap:anywhere;margin:6px 0}'
             '.unavailable,.stale,.unknown{color:#bbc3ce;background:#222a35}.badge{font-size:12px;border:1px solid #677487;border-radius:12px;padding:2px 8px}'
             '.eyebrow{color:#a7d5ff;font-size:12px;letter-spacing:.13em;text-transform:uppercase}nav{display:flex;gap:16px;flex-wrap:wrap}'
             '</style></head><body><main><header><p class="eyebrow">Private · offline preparation</p><h1>War room</h1>',
             f'<p>Saved sample <b>{esc(record["sample_at"])}</b> · assembled {esc(record["assembled_at"])}</p>',
             '<p>Live freshness, complete source history, scheduled operation and private hosting are Unverified. '
             'This file reloads every five minutes; only an explicit finite invocation creates a new sample.</p><nav>',
             *[f'<a href="#{g}">{esc(t)}</a>' for g, t in zip(suite.GROUPS, TITLES)], '</nav></header>']
    for group, title in zip(suite.GROUPS, TITLES):
        parts.append(f'<section id="{group}"><h2>{esc(title)}</h2>')
        for provider, definition in zip(record['providers'], suite.PROVIDERS):
            if group not in definition['groups']:
                continue
            metrics = [m for m in provider['metrics'] if m['group'] == group]
            parts.append(f'<div class="provider {esc(provider["state"])}" data-slot="{esc(provider["slot"])}">'
                         f'<h3>{esc(NAMES[provider["slot"]])} <span class="badge">{esc(provider["state"])}</span></h3>')
            parts.extend(f'<p class="detail">Prerequisite: {esc(p)}</p>' for p in provider['prerequisites'])
            parts.extend(metric_html(m) for m in metrics)
            if not metrics:
                parts.append('<p class="detail">No measured values for this group. Unknown, never zero.</p>')
            parts.append('</div>')
        if group == 'board':
            parts.append('<details><summary>Complete bench inventory</summary><ul>')
            parts.extend(f'<li>{esc(NAMES[p["slot"]])}: {esc(p["state"])}</li>' for p in record['providers'])
            parts.append('</ul></details>')
        parts.append('</section>')
    parts.append('</main></body></html>')
    return ''.join(parts)
