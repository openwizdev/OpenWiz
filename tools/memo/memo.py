#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCHEMA = 'openwiz.memo.v1'
PIN = 'a679d322cf7723185f14603a67595bf0bdf98c69'
UPSTREAM = 'https://github.com/arunv3rma/MeMo.git'
SYNTHESIS = (
    'fact extraction',
    'consolidation',
    'verification',
    'entity surfacing',
    'cross-document synthesis',
)
KEYS = {
    'api_key_env', 'corpus', 'enabled', 'endpoint', 'experimental', 'fallback',
    'include_brain', 'max_passages', 'model', 'schema', 'timeout_seconds',
}
SUFFIXES = {'.md', '.txt', '.markdown'}
STOP = frozenset(
    'a an the of to and or in on for is it be as at by we you our from with that this'.split())
WORD = re.compile(r'[a-z0-9]{2,}')
MODEL = re.compile(r'[A-Za-z0-9_.:/+-]{1,100}')
ENV_NAME = re.compile(r'[A-Z_][A-Z0-9_]{0,63}')
MAX_FILE = 200_000
MAX_FILES = 2000
MAX_ANSWER = 8000
MAX_QUESTION = 2000
MAX_BODY = 1_000_000


class GiveUp(Exception):
    def __init__(self, code, kind, message):
        self.code, self.kind, self.message = code, kind, message


class EndpointFailure(Exception):
    def __init__(self, reason):
        self.reason = reason


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise EndpointFailure('endpoint_error')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GiveUp(2, 'usage', 'settings contain a duplicate key')
        result[key] = value
    return result


def defaults():
    return {
        'schema': SCHEMA,
        'experimental': True,
        'enabled': False,
        'endpoint': 'http://127.0.0.1:8000/v1',
        'model': 'memo',
        'timeout_seconds': 30,
        'api_key_env': None,
        'corpus': 'docs',
        'include_brain': True,
        'max_passages': 4,
        'fallback': 'retrieval',
    }


def check_endpoint(value):
    if (not isinstance(value, str) or not 8 <= len(value) <= 200
            or any(c.isspace() or ord(c) < 32 for c in value)):
        raise GiveUp(2, 'usage', 'endpoint must be an http(s) URL')
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password
            or not parsed.hostname or parsed.query or parsed.fragment):
        raise GiveUp(2, 'usage', 'endpoint must be an http(s) URL with no userinfo or query')


def check_corpus(value):
    if not isinstance(value, str) or not value or value.startswith(('/', '\\')) or '\\' in value:
        raise GiveUp(2, 'usage', 'corpus must be a relative folder')
    if '..' in Path(value).parts:
        raise GiveUp(2, 'usage', 'corpus must stay inside the project')


def read_settings(path):
    file = Path(path)
    if not file.is_file() or file.stat().st_size > 100_000:
        raise GiveUp(2, 'usage', 'settings file is missing or too large')
    try:
        data = json.loads(file.read_text(encoding='utf-8'), object_pairs_hook=unique)
    except GiveUp:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise GiveUp(2, 'usage', 'settings file is not JSON')
    if type(data) is not dict or set(data) != KEYS or data['schema'] != SCHEMA:
        raise GiveUp(2, 'usage', 'settings must be an openwiz.memo.v1 object')
    if data['experimental'] is not True:
        raise GiveUp(2, 'usage', 'experimental must be true')
    if type(data['enabled']) is not bool or type(data['include_brain']) is not bool:
        raise GiveUp(2, 'usage', 'enabled and include_brain must be booleans')
    if data['fallback'] != 'retrieval':
        raise GiveUp(2, 'usage', 'fallback must be retrieval')
    check_endpoint(data['endpoint'])
    if not isinstance(data['model'], str) or not MODEL.fullmatch(data['model']):
        raise GiveUp(2, 'usage', 'model must be 1 to 100 characters')
    if type(data['timeout_seconds']) is not int or not 1 <= data['timeout_seconds'] <= 120:
        raise GiveUp(2, 'usage', 'timeout_seconds must be from 1 to 120')
    if type(data['max_passages']) is not int or not 1 <= data['max_passages'] <= 8:
        raise GiveUp(2, 'usage', 'max_passages must be from 1 to 8')
    env_name = data['api_key_env']
    if env_name is not None and (not isinstance(env_name, str) or not ENV_NAME.fullmatch(env_name)):
        raise GiveUp(2, 'usage', 'api_key_env must name an environment variable')
    check_corpus(data['corpus'])
    return data


def settings_for(root, explicit):
    if explicit:
        return read_settings(explicit)
    path = Path(root) / 'docs' / 'agents' / 'memo.json'
    if path.is_file():
        return read_settings(path)
    return defaults()


def tokens(text):
    return {word for word in WORD.findall(text.lower()) if word not in STOP}


def passages_of(text):
    chunks, buf, size = [], [], 0
    for para in re.split(r'\n\s*\n', text):
        para = ' '.join(para.split())
        if not para:
            continue
        if size >= 800 and buf:
            chunks.append(' '.join(buf)[:800])
            buf, size = [], 0
        buf.append(para[:800])
        size += len(para)
    if buf:
        chunks.append(' '.join(buf)[:800])
    return chunks


def documents(root, settings):
    bases = [Path(root) / settings['corpus']]
    if settings['include_brain']:
        bases.append(Path(root) / '.openwiz' / 'brain')
    found = []
    for base in bases:
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(name for name in dirnames if not name.startswith('.'))
            for name in sorted(filenames):
                if len(found) >= MAX_FILES:
                    return found
                path = Path(dirpath) / name
                if path.suffix.lower() not in SUFFIXES or path.is_symlink():
                    continue
                try:
                    if path.stat().st_size > MAX_FILE:
                        continue
                    text = path.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    continue
                found.append((path.relative_to(root).as_posix(), text))
    return found


def retrieve(root, settings, question):
    wanted = tokens(question)
    scored = []
    for rel, text in documents(root, settings):
        for passage in passages_of(text):
            score = len(wanted & tokens(passage))
            if score:
                scored.append((-score, rel, passage))
    scored.sort()
    sources = [{'path': rel, 'text': passage} for _, rel, passage in scored[:settings['max_passages']]]
    if not sources:
        answer = 'The corpus does not cover that question.'
    else:
        answer = '\n\n'.join(source['path'] + '\n' + source['text'] for source in sources)
    return answer[:MAX_ANSWER], sources


def retrieval_report(root, settings, question, reason):
    answer, sources = retrieve(root, settings, question)
    return {
        'schema': 'openwiz.memo.answer.v1',
        'experimental': True,
        'backend': 'retrieval',
        'fallback_reason': reason,
        'answer': answer,
        'provenance': [source['path'] for source in sources],
        'sources': sources,
    }


def chat_url(endpoint):
    base = endpoint.rstrip('/')
    if base.endswith('/chat/completions'):
        return base
    return base + '/chat/completions'


def complete(settings, question):
    payload = {
        'model': settings['model'],
        'temperature': 0,
        'messages': [
            {'role': 'system', 'content': 'Answer from memory only.'},
            {'role': 'user', 'content': question},
        ],
    }
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    env_name = settings['api_key_env']
    if env_name:
        key = os.environ.get(env_name) or ''
        if key:
            headers['Authorization'] = 'Bearer ' + key
    request = urllib.request.Request(
        chat_url(settings['endpoint']),
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    try:
        with opener.open(request, timeout=settings['timeout_seconds']) as response:
            raw = response.read(MAX_BODY + 1)
            status = response.status
    except EndpointFailure:
        raise
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise EndpointFailure('endpoint_error')
    if status != 200 or len(raw) > MAX_BODY:
        raise EndpointFailure('endpoint_error')
    try:
        body = json.loads(raw.decode('utf-8'))
        text = body['choices'][0]['message']['content']
    except (UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        raise EndpointFailure('endpoint_error')
    if not isinstance(text, str) or not text.strip():
        raise EndpointFailure('empty')
    return text.strip()[:MAX_ANSWER]


def ask(root, settings, question):
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION or '\x00' in question:
        raise GiveUp(2, 'usage', 'the question must be 1 to 2000 characters')
    if not settings['enabled']:
        return retrieval_report(root, settings, question, 'disabled')
    try:
        text = complete(settings, question)
    except EndpointFailure as error:
        report = retrieval_report(root, settings, question, error.reason)
        return report
    return {
        'schema': 'openwiz.memo.answer.v1',
        'experimental': True,
        'backend': 'memo',
        'fallback_reason': None,
        'answer': text,
        'provenance': None,
        'sources': [],
    }


def status_report(settings):
    return {
        'schema': 'openwiz.memo.status.v1',
        'experimental': True,
        'enabled': settings['enabled'],
        'backend': 'memo' if settings['enabled'] else 'retrieval',
        'endpoint': settings['endpoint'],
        'model': settings['model'],
        'corpus': settings['corpus'],
        'include_brain': settings['include_brain'],
        'executive': 'any',
        'memo_provenance': None,
    }


def corpus_files(corpus):
    root = Path(corpus)
    if not root.is_dir():
        raise GiveUp(2, 'usage', 'the corpus folder is missing')
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith('.'))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() not in SUFFIXES or path.is_symlink():
                continue
            try:
                if path.stat().st_size > MAX_FILE:
                    continue
            except OSError:
                continue
            found.append(path)
            if len(found) >= MAX_FILES:
                return found
    if not found:
        raise GiveUp(2, 'usage', 'the corpus folder has no text or markdown files')
    return found


def plan_document(count):
    return {
        'schema': 'openwiz.memo.build-plan.v1',
        'experimental': True,
        'documents': count,
        'license': 'MIT',
        'repository': 'https://github.com/arunv3rma/MeMo',
        'pin': PIN,
        'synthesis': list(SYNTHESIS),
        'sft': 'sft_training/sft_lora_pipeline.py',
        'trains': False,
    }


def script_text():
    body = r"""#!/bin/sh
set -eu
PIN=__PIN__
ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
if [ "${OPENWIZ_MEMO_TRAIN:-}" != 1 ]; then
  printf '%s\n' 'MeMo training was not started.'
  exit 0
fi
if [ ! -f "$ROOT/reflection-qa.json" ]; then
  printf '%s\n' 'reflection-qa.json is missing. Run the upstream synthesis steps first.'
  exit 2
fi
if [ ! -d "$ROOT/MeMo/sft_training" ]; then
  rm -rf "$ROOT/MeMo"
  git init "$ROOT/MeMo"
  git -C "$ROOT/MeMo" remote add origin __UPSTREAM__
  git -C "$ROOT/MeMo" fetch --depth 1 origin "$PIN"
  git -C "$ROOT/MeMo" checkout --detach FETCH_HEAD
fi
cd "$ROOT/MeMo"
exec accelerate launch --config_file sft_training/accelerate_config.yaml sft_training/sft_lora_pipeline.py \
  --data_path "$ROOT/reflection-qa.json" \
  --model_name "${OPENWIZ_MEMO_BASE_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}" \
  --output_dir "$ROOT/checkpoint" \
  --val_split 0.0 \
  --num_train_epochs 1 \
  --per_device_batch_size 1 \
  --gradient_accumulation_steps 1 \
  --learning_rate 2e-4 \
  --lr_scheduler_type constant_with_warmup \
  --warmup_ratio 0.05 \
  --weight_decay 0.01 \
  --max_grad_norm 1.0 \
  --max_seq_length 4096 \
  --lora_r 8 \
  --lora_alpha 16 \
  --lora_dropout 0.05 \
  --lora_target_modules q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj \
  --logging_steps 10 \
  --save_only_model \
  --world_size 1 \
  --wandb_run_name openwiz-memo
"""
    return body.replace('__PIN__', PIN).replace('__UPSTREAM__', UPSTREAM)


def stage(corpus, out):
    destination = Path(out)
    files = corpus_files(corpus)
    staged = destination / 'corpus'
    if staged.exists():
        shutil.rmtree(staged)
    copied = []
    for path in files:
        rel = path.relative_to(corpus).as_posix()
        target = staged / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copied.append(rel)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'corpus.json').write_text(
        json.dumps({'files': copied}, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    script = destination / 'memo-build.sh'
    script.write_text(script_text(), encoding='utf-8')
    os.chmod(script, 0o755)
    plan = plan_document(len(copied))
    (destination / 'plan.json').write_text(
        json.dumps(plan, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return plan


def run_training(out):
    if os.environ.get('OPENWIZ_MEMO_TRAIN') != '1':
        raise GiveUp(2, 'usage', 'training stays off until OPENWIZ_MEMO_TRAIN=1 on a GPU machine')
    script = Path(out) / 'memo-build.sh'
    result = subprocess.run(['/bin/sh', str(script)], capture_output=True, text=True)
    note = (result.stdout + result.stderr).strip()[-2000:]
    return result.returncode, note


def emit(document):
    sys.stdout.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + '\n')


def fail(error):
    emit({
        'schema': 'openwiz.cli-error.v1',
        'command': 'memo',
        'exit_code': error.code,
        'error': {'kind': error.kind, 'message': error.message},
    })
    return error.code


def command_ask(args):
    settings = settings_for(args.root, args.settings)
    emit(ask(args.root, settings, args.question))
    return 0


def command_status(args):
    emit(status_report(settings_for(args.root, args.settings)))
    return 0


def command_build(args):
    if args.execute and args.train:
        raise GiveUp(2, 'usage', 'build takes one of --execute or --train')
    if (args.execute or args.train) and not args.out:
        raise GiveUp(2, 'usage', 'build --execute and --train need --out')
    if args.out:
        corpus = Path(args.corpus).resolve()
        out = Path(args.out).resolve()
        if out == corpus or corpus in out.parents:
            raise GiveUp(2, 'usage', 'the output folder must sit outside the corpus')
    count = len(corpus_files(args.corpus))
    if not args.execute and not args.train:
        emit(plan_document(count))
        return 0
    plan = stage(args.corpus, args.out)
    if args.execute:
        emit({
            'schema': 'openwiz.memo.build.v1',
            'experimental': True,
            'mode': 'execute',
            'pin': PIN,
            'out': str(Path(args.out).resolve()),
            'documents': plan['documents'],
            'trains': False,
            'script_exit': None,
        })
        return 0
    code, note = run_training(args.out)
    emit({
        'schema': 'openwiz.memo.build.v1',
        'experimental': True,
        'mode': 'train',
        'pin': PIN,
        'out': str(Path(args.out).resolve()),
        'documents': plan['documents'],
        'trains': code == 0,
        'script_exit': code,
        'note': note,
    })
    return code


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--root', default='.')
    common.add_argument('--settings')
    tool = argparse.ArgumentParser(prog='memo.py')
    commands = tool.add_subparsers(dest='command', required=True)
    ask_command = commands.add_parser('ask', parents=[common])
    ask_command.add_argument('question')
    ask_command.set_defaults(run=command_ask)
    status_command = commands.add_parser('status', parents=[common])
    status_command.set_defaults(run=command_status)
    build_command = commands.add_parser('build', parents=[common])
    build_command.add_argument('--corpus', required=True)
    build_command.add_argument('--out')
    build_command.add_argument('--execute', action='store_true')
    build_command.add_argument('--train', action='store_true')
    build_command.set_defaults(run=command_build)
    return tool


def main(argv):
    try:
        args = parser().parse_args(argv)
        return args.run(args)
    except GiveUp as error:
        return fail(error)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
