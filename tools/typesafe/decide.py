import json
from pathlib import Path

import client

PATH = Path(__file__).with_name('config.json')


def load():
    return json.loads(PATH.read_text())


def questions(site_name):
    return load()['sites'][site_name]['questions']


def uncertain_noul(value, root=None):
    root = load() if root is None else root
    return root['noul']['no'] < value < root['noul']['yes']


def signal(response, site, root=None):
    root = load() if root is None else root
    parts = []
    for term in site['terms']:
        value = client.noul(response, term['question'])
        if uncertain_noul(value, root):
            return None
        if term.get('invert'):
            value = 1.0 - value
        parts.append((float(term['weight']), value))
    kind = site['combine']
    if kind == 'weighted_sum':
        return sum(weight * value for weight, value in parts)
    if kind == 'noisy_or':
        product = 1.0
        for weight, value in parts:
            product *= 1.0 - min(1.0, max(0.0, weight * value))
        return 1.0 - product
    raise client.TypeSafeError('shape')


def choice_ready(response, name, confidence_at):
    picked, probability, confidence = client.choice(response, name)
    if confidence < confidence_at:
        return None
    return picked, probability, confidence


def score_ready(response, name, confidence_at):
    value, confidence, probabilities, legend = client.score(response, name)
    if confidence < confidence_at:
        return None
    return value, confidence, probabilities, legend


def box_ready(response, name, confidence_at):
    edges, confidence = client.box(response, name)
    if confidence < confidence_at:
        return None
    return edges, confidence
