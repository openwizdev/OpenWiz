"""Offline fixed-horizon estimators; all choices must be frozen in EB5 prose.

No collector, fitting of favorable methods, dispatch or execution authority.
See docs/agents/skills-ab.md for estimands, assumptions and source formulas.
"""
import copy
from datetime import timedelta
import importlib.util
import math
from pathlib import Path
import re
from statistics import NormalDist, mean, variance
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('offline_controls', HERE / 'controls.py')
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)
C = E.C


def probability(alpha):
    C.number(alpha)
    C.require(0 < alpha < 1, 'probability outside (0,1)')


def power_plan(power, guards):
    """Normal planning approximation plus the independently reviewed guard minima."""
    for k in ('alpha', 'power'):
        probability(power[k])
    C.require(power['method'] == 'normal-mean-planning-v1', 'unsupported power method')
    C.require(power['power'] >= .5, 'planning power must be at least .5')
    for k in ('effect_hours', 'baseline_sd_hours'):
        C.number(power[k])
        C.require(power[k] > 0, 'positive variability/effect required')
    C.integer(power['baseline_n'], 2)
    C.integer(power['baseline_unknown'])
    za = NormalDist().inv_cdf(1-power['alpha']/2)
    zp = NormalDist().inv_cdf(power['power'])
    n = math.ceil(2*(za+zp)**2*power['baseline_sd_hours']**2/power['effect_hours']**2)
    minima = []
    for k in ('rounds', 'defects'):
        C.integer(guards[k]['min_n_per_arm'], 2)
        C.number(guards[k]['max_interval_width'])
        C.require(guards[k]['max_interval_width'] > 0 and guards[k]['margin'] == 0,
                  'guard precision and non-worsening required')
        minima.append(guards[k]['min_n_per_arm'])
    return dict(z_alpha=za, z_power=zp, time_n_per_arm=n, min_n_per_arm=max(n, *minima))


def effect(unit, old, candidate, interval):
    delta = candidate-old
    return dict(unit=unit, old=old, candidate=candidate, delta=delta,
                percent=100*delta/old if old else None, interval=interval)


def _beta_fraction(a, b, x):
    # Modified Lentz evaluation of the incomplete-beta continued fraction.
    # Refuse nonconvergence instead of substituting a normal critical value.
    tiny = 1e-300
    def nonzero(v):
        return v if abs(v) > tiny else math.copysign(tiny, v)
    c, d = 1., 1./nonzero(1-(a+b)*x/(a+1))
    h = d
    for m in range(1, 401):
        for coefficient in (m*(b-m)*x/((a+2*m-1)*(a+2*m)),
                            -(a+m)*(a+b+m)*x/((a+2*m)*(a+2*m+1))):
            d = 1./nonzero(1+coefficient*d)
            c = nonzero(1+coefficient/c)
            change = d*c
            h *= change
        if abs(change-1) < 1e-13:
            return h
    raise ValueError('Student interval did not converge')


def _beta(a, b, x):
    if x <= 0:
        return 0.
    if x >= 1:
        return 1.
    front = math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)
                     + a*math.log(x)+b*math.log1p(-x))
    if x < (a+1)/(a+b+2):
        return front*_beta_fraction(a,b,x)/a
    return 1-front*_beta_fraction(b,a,1-x)/b


def t_critical(alpha, df):
    probability(alpha)
    C.number(df, 1)
    def tail(t):
        return .5*_beta(df/2, .5, df/(df+t*t))
    lo, hi = 0., 1.
    while tail(hi) > alpha/2:
        hi *= 2
        C.require(math.isfinite(hi*hi), 'Student interval overflow')
    for _ in range(80):
        mid = (lo+hi)/2
        if tail(mid) > alpha/2:
            lo = mid
        else:
            hi = mid
    return (lo+hi)/2


def mean_effect(old, candidate, alpha):
    """Welch-Satterthwaite interval for independent per-ticket round counts."""
    probability(alpha)
    for v in [*old, *candidate]:
        C.number(v)
    if min(len(old), len(candidate)) < 2:
        return E.unknown_effect('rounds')
    vo, vc = variance(old)/len(old), variance(candidate)/len(candidate)
    if vo+vc == 0:
        return E.unknown_effect('rounds')
    df = (vo+vc)**2/(vo**2/(len(old)-1)+vc**2/(len(candidate)-1))
    radius = t_critical(alpha, df)*math.sqrt(vo+vc)
    o, c = mean(old), mean(candidate)
    return effect('rounds', o, c, [c-o-radius, c-o+radius])


def _wilson(events, n, z):
    p = events/n
    denominator = 1+z*z/n
    center = (p+z*z/(2*n))/denominator
    radius = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denominator
    return max(0., min(p, center-radius)), min(1., max(p, center+radius))


def risk_effect(old, candidate, alpha):
    """Difference of Bonferroni component Wilson intervals; zero events stay wide."""
    probability(alpha)
    for events, n in (old, candidate):
        C.integer(events)
        C.integer(n)
        C.require(events <= n, 'risk numerator exceeds denominator')
    if not old[1] or not candidate[1]:
        return E.unknown_effect('proportion')
    z = NormalDist().inv_cdf(1-alpha/4)
    ol, ou = _wilson(*old, z)
    cl, cu = _wilson(*candidate, z)
    return effect('proportion', old[0]/old[1], candidate[0]/candidate[1], [cl-ou, cu-ol])


def bounded_effect(old, candidate, tau, alpha):
    """Partial-identification bounds for E[min(merge hours,tau)], every ticket.

    Each pair is the lower/upper value compatible with that ticket's observed
    censoring. Upper-bound imputation is labelled, and the CI spans *all*
    compatible completions, expanded by the two-sample Hoeffding bound.
    """
    probability(alpha)
    C.number(tau)
    C.require(tau > 0, 'positive restriction required')
    for lo, hi in [*old, *candidate]:
        C.number(lo)
        C.number(hi)
        C.require(lo <= hi <= tau, 'invalid censoring bound')
    if not old or not candidate:
        return E.unknown_effect('hours'), None
    limits = {arm: [mean(lo for lo, _ in rows), mean(hi for _, hi in rows)]
              for arm, rows in (('old', old), ('candidate', candidate))}
    lower = limits['candidate'][0]-limits['old'][1]
    upper = limits['candidate'][1]-limits['old'][0]
    limits['delta'] = [lower, upper]
    radius = tau*math.sqrt(.5*math.log(2/alpha)*(1/len(old)+1/len(candidate)))
    interval = [max(-tau, lower-radius), min(tau, upper+radius)]
    return effect('hours', limits['old'][1], limits['candidate'][1], interval), limits


def methods(protocol):
    primary = protocol['primary']
    match = re.fullmatch(r'restricted-mean-hours-v1 tau=([0-9]+(?:\.[0-9]+)?)', primary['statistic'])
    C.require(match is not None and primary['test'] == 'bounded-mean-hoeffding-v1'
        and primary['unfinished'] == 'right-censor-at-horizon; closed-unmerged=tau; all-assigned'
        and primary['missing'] == 'unknown-effect; censoring-bounds; parity-is-not-random'
        and protocol['guards']['rounds']['test'] == 'welch-independent-rounds-v1'
        and protocol['guards']['defects']['test'] == 'bonferroni-wilson-risk-difference-v1',
        'unsupported frozen analysis method; do not relabel an approved protocol')
    tau = float(match[1])
    C.number(tau)
    C.require(tau > 0, 'positive restriction required')
    return tau


def analyze(bundle, journey, *, at):
    """Return (new EB5 bundle, explanatory diagnostics), never a live verdict."""
    out = E.advance(bundle, journey, copy.deepcopy(bundle), journey, at=at)
    detail = dict(censoring={}, sensitivity=None, limitations=[
        'Synthetic/offline analysis is not a live result or evidence verification.',
        'Parity is deterministic; intervals assume independent comparable units, not random assignment.',
        'Normal time planning is approximate; guard minima require independent precision review.',
        'Round intervals use a normal-sample Welch approximation; Wilson coverage is approximate.',
        'v1 has no sourced closure-by-horizon evidence; current closure is separate from horizon censoring.'])
    if out['result'] is not None:
        detail['limitations'].append('Terminal result retained; no resumption or efficacy peeking.')
        return out, detail
    p = out['preregistration']
    C.require(C.time(at) >= C.time(p['horizon']), 'no efficacy analysis before fixed horizon')
    tau, alpha = methods(p), p['power']['alpha']
    sample, rows = E.samples(out, journey, at=p['horizon'])
    prs = {pr['number']: pr for pr in journey['pull_requests']}
    round_index = E.canonical_rounds(journey)
    times, rounds, risks = {}, {}, {}
    ambiguous = False
    for arm in C.ARMS:
        time_bounds, round_values, defect_values = [], [], []
        counts = dict(right_censored=0, closed_unmerged=0, unknown_timing=0,
                      current_closed_unmerged=0, closure_by_horizon='unavailable')
        sample[arm]['mature_defects'] = 0
        for row in rows[arm]:
            m, category = row['measurement'], row['category']
            counts['current_closed_unmerged'] += row['current_closed_unmerged']
            if m is None or len(prs[m['pr']]['tickets']) != 1:
                ambiguous = True
            if not row['timing_known'] or m is None:
                counts['unknown_timing'] += 1
                time_bounds.append(None)
            elif category == 'merged':
                elapsed = (C.time(m['merge']['at'])-C.time(m['first_push']['at'])).total_seconds()/3600
                time_bounds.append((min(tau, elapsed),)*2)
            else:
                counts['right_censored'] += 1
                elapsed = (C.time(p['horizon'])-C.time(m['first_push']['at'])).total_seconds()/3600
                time_bounds.append((min(tau, elapsed), tau))
            round_values.append(sum(C.J.rounds_of(e) and C.time(e['at']) <= C.time(p['horizon'])
                                    for e in round_index[m['pr']]) if m is not None else None)
            mature = bool(category == 'merged' and m is not None and m['defects']['status'] == 'mature'
                and C.time(m['merge']['at'])+timedelta(hours=out['experiment']['defect_policy']['followup_hours']) <= C.time(at))
            sample[arm]['mature_defects'] += mature
            if not mature:
                defect_values.append(None)
                continue
            defects = copy.deepcopy(m['defects'])
            defects['resolutions'] = [r for r in defects['resolutions'] if C.time(r['at']) <= C.time(at)]
            attribution = C.defect_attributions(defects)
            if any(v == 'unknown' for v in attribution.values()):
                defect_values.append(None)
            else:
                defect_values.append(int(any(v == 'attributable' for v in attribution.values())))
        detail['censoring'][arm] = counts
        times[arm], rounds[arm], risks[arm] = time_bounds, round_values, defect_values
    effects = {name: E.unknown_effect(unit) for name, unit in
               (('time','hours'),('rounds','rounds'),('defects','proportion'))}
    if not ambiguous:
        if all(None not in times[arm] for arm in C.ARMS):
            effects['time'], detail['sensitivity'] = bounded_effect(times['old'], times['candidate'], tau, alpha)
        if all(None not in rounds[arm] for arm in C.ARMS):
            effects['rounds'] = mean_effect(rounds['old'], rounds['candidate'], alpha)
        if all(None not in risks[arm] for arm in C.ARMS):
            effects['defects'] = risk_effect((sum(risks['old']),len(risks['old'])),
                                            (sum(risks['candidate']),len(risks['candidate'])), alpha)
    else:
        detail['limitations'].append('Shared/multiple PR unit: effects unknown, no independence claim.')
    eligible = all(s['assigned'] >= p['power']['min_n_per_arm'] and s['unknown_timing'] == 0
                   and s['mature_defects'] == s['merged'] for s in sample.values())
    time = effects['time']['interval']
    guards = [effects[g]['interval'] for g in ('rounds', 'defects')]
    harm = any(interval is not None and interval[0] > 0 for interval in guards)
    safe = all(interval is not None and interval[1] <= 0 and
               interval[1]-interval[0] <= p['guards'][name]['max_interval_width']
               for name, interval in zip(('rounds','defects'), guards))
    material = any(d['material'] for d in out['deviations'])
    verdict = 'harm' if harm else ('improved' if eligible and safe and time is not None and time[1] < 0
                                  and not material else 'inconclusive')
    out['result'] = dict(at=at, preregistration_hash=C.preregistration_digest(p),
        status='inconclusive' if verdict == 'inconclusive' else 'complete', verdict=verdict,
        samples=sample, effects=effects, stops=[])
    E.transition(bundle, out, journey, journey)
    return out, detail
