"""Webhook auth tests. Calls the handler directly; no network or MT5."""
import asyncio
import ast
import tempfile
import unittest
from pathlib import Path
from fastapi import HTTPException
from state import GridState
from server import TradingServer, TokenError, load_token

TOKEN = 'A' * 16 + 'b-_9' * 4


def post(server, data):
    return asyncio.run(server.webhook(data))


class WebhookAuthTests(unittest.TestCase):
    def setUp(self):
        self.state = GridState()
        self.server = TradingServer(self.state, TOKEN)

    def assertRejected(self, data, status):
        with self.assertRaises(HTTPException) as ctx:
            post(self.server, data)
        self.assertEqual(ctx.exception.status_code, status)
        self.assertFalse(self.state.is_new_request)

    def test_valid_token_updates_zone(self):
        result = post(self.server, {'min': 2300.5, 'max': 2310, 'direction': 'SELL', 'token': TOKEN})
        self.assertEqual(result, {'status': 'received', 'direction': 'sell', 'zone': [2300.5, 2310.0]})
        self.assertTrue(self.state.is_new_request)
        self.assertEqual((self.state.min_price, self.state.max_price, self.state.direction), (2300.5, 2310.0, 'sell'))

    def test_missing_wrong_or_non_string_token_is_rejected(self):
        for token in (None, '', TOKEN[:-1], TOKEN + 'x', 123, [TOKEN]):
            with self.subTest(token=token):
                data = {'min': 1, 'max': 2, 'direction': 'buy'}
                if token is not None:
                    data['token'] = token
                self.assertRejected(data, 401)

    def test_bad_prices_are_rejected_after_auth(self):
        for data in ({}, {'min': 1}, {'min': 'x', 'max': 2}, {'min': None, 'max': 2},
                     {'min': float('nan'), 'max': 2}, {'min': 1, 'max': float('inf')}):
            with self.subTest(data=data):
                self.assertRejected({**data, 'token': TOKEN}, 400)

    def test_token_is_not_logged(self):
        from unittest.mock import patch
        with patch('builtins.print') as printed:
            post(self.server, {'min': 1, 'max': 2, 'token': TOKEN})
            with self.assertRaises(HTTPException):
                post(self.server, {'min': 1, 'max': 2, 'token': 'wrong-' + TOKEN})
        logged = ' '.join(str(a) for call in printed.call_args_list for a in call.args)
        self.assertNotIn(TOKEN, logged)

    def test_server_requires_token(self):
        for token in ('', None):
            with self.assertRaises(TokenError):
                TradingServer(self.state, token)

    def test_binds_loopback_only(self):
        tree = ast.parse(Path(__file__).resolve().parents[1].joinpath('server.py').read_text(encoding='utf-8'))
        hosts = [kw.value.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                 for kw in node.keywords if kw.arg == 'host']
        self.assertEqual(hosts, ['127.0.0.1'])


class LoadTokenTests(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile('w', suffix='.token', delete=False, encoding='utf-8')
        handle.write(text)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_valid_token_is_stripped(self):
        self.assertEqual(load_token(self.write(TOKEN + '\r\n')), TOKEN)

    def test_missing_short_or_unsafe_token_is_refused(self):
        with self.assertRaises(TokenError):
            load_token(str(Path(tempfile.gettempdir()) / 'no-such-xau-token'))
        for bad in ('', 'a' * 31, TOKEN + '"', TOKEN + ' x', TOKEN + '\\', 'あ' * 40):
            with self.subTest(bad=bad), self.assertRaises(TokenError):
                load_token(self.write(bad))


if __name__ == '__main__':
    unittest.main()
