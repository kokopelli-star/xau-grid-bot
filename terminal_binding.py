"""Inert fixed-terminal identity checks. No credentials, login or auto discovery."""
import hashlib
import json
import ntpath
import threading


class BindingError(RuntimeError):
    pass


class RequestNotSent(BindingError):
    """A final preflight rejected the request before native invocation."""


def canonical_path(value):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise BindingError('terminal binding path required')
    drive, tail = ntpath.splitdrive(value)
    if len(drive) != 2 or drive[1] != ':' or not tail.startswith(('\\', '/')):
        raise BindingError('absolute local Windows path required')
    return ntpath.normcase(ntpath.normpath(value))


class TerminalSpec:
    KEYS = {'terminal_exe_path', 'terminal_data_path', 'expected_account_login', 'expected_account_server'}

    def __init__(self, values):
        if not isinstance(values, dict) or set(values) != self.KEYS:
            raise BindingError('exact terminal binding fields required')
        self.exe = canonical_path(values['terminal_exe_path'])
        self.data = canonical_path(values['terminal_data_path'])
        if ntpath.basename(self.exe) not in ('terminal64.exe', 'metatrader64.exe'):
            raise BindingError('supported MT5 executable required')
        self.installation = ntpath.dirname(self.exe)
        self.login = values['expected_account_login']
        self.server = values['expected_account_server']
        if type(self.login) is not int or self.login <= 0 or not isinstance(self.server, str) or not self.server.strip():
            raise BindingError('expected account identity required')
        self.fingerprint = hashlib.sha256(json.dumps([self.exe, self.data, self.login, self.server],
                                                     separators=(',', ':')).encode()).hexdigest()

    @classmethod
    def from_config(cls, config):
        return cls({key:getattr(config, key) for key in cls.KEYS})

    @classmethod
    def load(cls, path):
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result: raise BindingError('duplicate binding field')
                    result[key] = value
                return result
            with open(path, encoding='utf-8-sig') as stream:
                return cls(json.load(stream, object_pairs_hook=unique))
        except Exception:
            raise BindingError('terminal binding file invalid; details withheld') from None


class TerminalBinding:
    def __init__(self, spec, target):
        self.spec, self.target = spec, target
        self.failed = False
        self.lock = threading.RLock()

    def stop(self):
        with self.lock:
            self.failed = True

    def check(self, api, trading=False):
        with self.lock:
            try:
                if self.failed or not self.target.alive() or canonical_path(self.target.path) != self.spec.exe:
                    raise BindingError('terminal process changed')
                # Two observations reduce (but cannot eliminate) manual account-switch races.
                for _ in range(2):
                    terminal, account = api.terminal_info(), api.account_info()
                    if (terminal is None or account is None or terminal.connected is not True
                        or canonical_path(terminal.path) != self.spec.installation
                        or canonical_path(terminal.data_path) != self.spec.data
                        or type(account.login) is not int or account.login != self.spec.login
                        or account.server != self.spec.server):
                        raise BindingError('terminal or account mismatch')
                    if trading and (terminal.trade_allowed is not True
                        or getattr(terminal, 'tradeapi_disabled', True) is not False
                        or account.trade_allowed is not True or account.trade_expert is not True):
                        raise BindingError('trading permission unavailable')
                if not self.target.alive(): raise BindingError('terminal exited')
            except Exception:
                self.failed = True
                raise BindingError('terminal/account guard stopped; local review and restart required') from None

    def send(self, api, request, before_send=None):
        with self.lock:
            self.check(api, trading=True)
            if before_send is not None:
                before_send()
            try:
                result = api.order_send(request)
                self.check(api, trading=True)
                return result
            except Exception:
                self.failed = True
                # This exception follows a potentially executed request. Never retry it blindly.
                raise BindingError('sent request outcome unknown; guard stopped; reconcile before restart') from None
