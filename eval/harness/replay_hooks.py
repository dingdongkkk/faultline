"""Offline replay of saved tool results through current hooks. No model/test runs.

Usage: PYTHONPATH=src python eval/harness/replay_hooks.py --repo ... --logs ...
Original logs and recorded repair metrics are never rewritten.
"""
import argparse
import json
from pathlib import Path
from faultline.claude import context


def replay(repo, logs):
    records = []
    for path in sorted(Path(logs).glob('*H*.events.jsonl')):
        record = {'session': path.name, 'old_hook_output_bytes': 0, 'responses': []}
        tool_names = {}
        for line in path.read_text().splitlines():
            e = json.loads(line)
            if e.get('subtype') == 'hook_response':
                record['old_hook_output_bytes'] += len(e.get('output', '').encode())
            message = e.get('message')
            blocks = message.get('content', []) if isinstance(message, dict) else []
            if not isinstance(blocks, list):
                continue
            for b in blocks:
                if isinstance(b, dict) and b.get('type') == 'tool_use':
                    tool_names[b['id']] = b.get('name')
                if not isinstance(b, dict) or b.get('type') != 'tool_result' or not isinstance(b.get('content'), str):
                    continue
                if tool_names.get(b.get('tool_use_id')) != 'Bash':
                    continue
                # Offline reconstruction of Bash hook input; not live client delivery.
                text = context(repo, {'cwd': repo, 'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                                      'tool_response': {'stdout': b['content']}})
                if text:
                    record['responses'].append({'bytes': len(text.encode()), 'context': text})
        records.append(record)
    return {'kind': 'offline_saved_output_replay', 'live_client': False, 'repair_token_saving_measured': False,
            'records': records}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--repo', required=True)
    p.add_argument('--logs', required=True)
    args = p.parse_args()
    print(json.dumps(replay(args.repo, args.logs), indent=2))
