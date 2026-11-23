import json
import os


class Host:
    pass


def status(host, state_dir):
    with open(os.environ['SYNTHETIC_SCENARIO'], encoding='utf-8') as handle:
        scenario = json.load(handle)
    return {'code': 'cloudroom_login_verified' if scenario.get('cloudroom') == 'ok' else 'cloudroom_login_missing'}
