"""Unit tests for the deterministic pre-localization cell (pure functions)."""

from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ranker_prelocalize import build_command, format_report


class TestFormatReport(unittest.TestCase):
    def test_ok_payload_with_results_and_snippets(self):
        payload = {
            'status': 'ok', 'mode': 'full', 'candidate_count': 200, 'seconds': 28.3,
            'results': [
                {'symbol': 'fastapi.routing.get_request_handler', 'path': 'fastapi/routing.py',
                 'start_line': 100, 'end_line': 130, 'score': 1.5, 'snippet': 'def get_request_handler(...)'},
                {'symbol': 'fastapi.applications.FastAPI', 'path': 'fastapi/applications.py',
                 'start_line': 1, 'end_line': 5, 'score': 1.1, 'snippet': None},
            ],
        }
        text = format_report(payload)
        self.assertTrue(text.startswith('ranker ok, mode full, 200 candidates, 28.3s'))
        self.assertIn('1. fastapi.routing.get_request_handler  fastapi/routing.py:100-130  score 1.5', text)
        self.assertIn('snippet of fastapi.routing.get_request_handler:', text)
        self.assertNotIn('snippet of fastapi.applications.FastAPI:', text)

    def test_error_payload(self):
        self.assertEqual(format_report({'status': 'error', 'error': 'boom'}),
                         'ranker error: boom')
        self.assertEqual(format_report({}), 'ranker error: unknown failure')
        self.assertEqual(format_report('not a dict'), 'ranker error: ')

    def test_empty_results(self):
        text = format_report({'status': 'ok', 'mode': 'lexical', 'candidate_count': 0,
                              'seconds': 1.0, 'results': []})
        self.assertEqual(text, 'ranker ok, mode lexical, 0 candidates, 1.0s')


class TestBuildCommand(unittest.TestCase):
    def test_command_structure_and_quoting(self):
        issue = 'fix the `anyOf` bug\nwith "quotes" and $dollar signs'
        b64 = base64.b64encode(issue.encode('utf-8')).decode('ascii')
        cmd = build_command(b64)
        self.assertTrue(cmd.startswith('cd /workspace && python3 /tmp/ranker-skill/scripts/localize.py'))
        self.assertIn('--root /workspace', cmd)
        self.assertIn(f'--issue "$(printf %s {b64} | base64 -d)"', cmd)
        self.assertIn('> /tmp/ranker-report.json 2> /tmp/ranker-error.txt', cmd)
        self.assertIn('echo PRELOC_EXIT:$?', cmd)
        # round trip: the base64 payload must decode back to the exact issue
        token = cmd.split('printf %s ')[1].split(' | base64')[0]
        self.assertEqual(base64.b64decode(token).decode('utf-8'), issue)

    def test_ascii_only_payload(self):
        issue = '中文内容 \U0001f41b emoji'
        b64 = base64.b64encode(issue.encode('utf-8')).decode('ascii')
        cmd = build_command(b64)
        # everything between printf and base64 -d is ASCII, so the shell line is safe
        self.assertEqual(token_for(cmd), b64)
        self.assertEqual(base64.b64decode(token_for(cmd)).decode('utf-8'), issue)


def token_for(cmd: str) -> str:
    return cmd.split('printf %s ')[1].split(' | base64')[0]


if __name__ == '__main__':
    unittest.main()
