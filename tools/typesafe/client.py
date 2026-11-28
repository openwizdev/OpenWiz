import json
import os
import urllib.error
import urllib.request

ENV = 'TYPESAFE_API_KEY'
OPT_IN = 'OPENWIZ_JEV'
URL = 'https://api.typesafe.ai/v1/systemone'
MODEL = 'jev-1.14.0'
MAX_STATE_CHARS = 24000
TIMEOUT_S = 10


class TypeSafeError(Exception):
    pass


class SystemOne:
    def system_one(self, state, questions, model=MODEL):
        raise NotImplementedError


def bounded(state):
    if isinstance(state, str) and len(state) > MAX_STATE_CHARS:
        return state[:MAX_STATE_CHARS]
    return state


def _finite(value):
    return type(value) in (int, float) and value == value and value not in (float('inf'), float('-inf'))


class HttpClient(SystemOne):
    def __init__(self, key, url=URL, timeout=TIMEOUT_S, post=None):
        if not isinstance(key, str) or not key.strip():
            raise TypeSafeError('key')
        self._key = key.strip()
        self._url = url
        self._timeout = timeout
        self._post = post or _urlopen

    def __repr__(self):
        return 'HttpClient()'

    def system_one(self, state, questions, model=MODEL):
        if not isinstance(questions, dict) or not questions:
            raise TypeSafeError('shape')
        body = json.dumps(
            {'model': model, 'state': bounded(state), 'questions': questions},
            ensure_ascii=False, allow_nan=False,
        ).encode('utf-8')
        headers = {
            'Authorization': 'Bearer ' + self._key,
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json',
        }
        try:
            status, raw = self._post(self._url, body, headers, self._timeout)
        except TypeSafeError:
            raise
        except Exception:
            raise TypeSafeError('network')
        if status != 200:
            raise TypeSafeError('http')
        try:
            parsed = json.loads(raw.decode('utf-8'))
        except (UnicodeError, ValueError):
            raise TypeSafeError('shape')
        if not isinstance(parsed, dict) or not isinstance(parsed.get('answers'), dict):
            raise TypeSafeError('shape')
        return parsed


class FakeClient(SystemOne):
    def __init__(self, answers=None, error=None, model=MODEL):
        self._answers = answers
        self._error = error
        self._model = model
        self.calls = []

    def system_one(self, state, questions, model=MODEL):
        self.calls.append({'state': state, 'questions': questions, 'model': model})
        if self._error:
            raise TypeSafeError(self._error)
        return {'model': self._model, 'answers': self._answers or {}, 'usage': {'input_tokens': 0, 'output_tokens': 0}}


def opted_in():
    return os.environ.get(OPT_IN) == '1'


def from_env():
    if not opted_in():
        return None
    key = os.environ.get(ENV, '')
    if not isinstance(key, str) or not key.strip():
        return None
    return HttpClient(key)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urlopen(url, body, headers, timeout):
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        _discard_error_page(e)
        return e.code, b''


def _discard_error_page(error):
    try:
        error.read()
    except Exception:
        pass


def noul(response, name):
    answer = _answer(response, name, 'noul')
    value = answer.get('noul')
    if not _finite(value) or not 0 <= value <= 1:
        raise TypeSafeError('shape')
    return float(value)


def choice(response, name):
    answer = _answer(response, name, 'choice')
    name_of = answer.get('choice')
    probabilities = answer.get('probabilities')
    confidence = answer.get('confidence')
    if not isinstance(name_of, str) or not isinstance(probabilities, dict) or not _finite(confidence):
        raise TypeSafeError('shape')
    if not 0 <= confidence <= 1:
        raise TypeSafeError('shape')
    probability = probabilities.get(name_of)
    if not _finite(probability) or not 0 <= probability <= 1:
        raise TypeSafeError('shape')
    return name_of, float(probability), float(confidence)


def score(response, name):
    answer = _answer(response, name, 'score')
    value = answer.get('score')
    confidence = answer.get('confidence')
    probabilities = answer.get('probabilities')
    legend = answer.get('legend')
    if (not _finite(value) or not _finite(confidence) or not isinstance(probabilities, dict)
            or not isinstance(legend, dict)):
        raise TypeSafeError('shape')
    if not 0 <= confidence <= 1 or not probabilities:
        raise TypeSafeError('shape')
    for probability in probabilities.values():
        if not _finite(probability) or not 0 <= probability <= 1:
            raise TypeSafeError('shape')
    return float(value), float(confidence), probabilities, legend


def box(response, name):
    answer = _answer(response, name, 'box')
    edges = answer.get('box')
    confidence = answer.get('confidence')
    if not isinstance(edges, dict):
        raise TypeSafeError('shape')
    if confidence is not None and (not _finite(confidence) or not 0 <= confidence <= 1):
        raise TypeSafeError('shape')
    found = {}
    for edge in ('top', 'bottom', 'left', 'right'):
        value = edges.get(edge)
        if not _finite(value) or not 0 <= value <= 1:
            raise TypeSafeError('shape')
        found[edge] = float(value)
    return found, None if confidence is None else float(confidence)


def _answer(response, name, kind):
    if not isinstance(response, dict):
        raise TypeSafeError('shape')
    answers = response.get('answers')
    if not isinstance(answers, dict) or name not in answers:
        raise TypeSafeError('shape')
    answer = answers[name]
    if not isinstance(answer, dict) or answer.get('type') != kind:
        raise TypeSafeError('shape')
    return answer
