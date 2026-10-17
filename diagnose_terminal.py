"""Read-only terminal identity diagnostic. No trading module import or order API."""
import argparse
import importlib
import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from terminal_binding import TerminalSpec, TerminalBinding
from terminal_process import find_running_terminal


def run(spec, attach_running=False, pid=None, importer=None, finder=None, platform_name=None):
    result = {'matched':False, 'reason':'explicit_existing_windows_terminal_required'}
    if not attach_running or (sys.platform if platform_name is None else platform_name) != 'win32':
        return result
    api = None
    target = None
    attempted = False
    try:
        target = (finder or find_running_terminal)(pid, expected_path=spec.exe)
        if not target.alive(): raise RuntimeError()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            api = (importer or importlib.import_module)('MetaTrader5')
            attempted = True
            if not target.alive() or api.initialize(spec.exe, timeout=10000) is not True:
                raise RuntimeError()
            binding = TerminalBinding(spec, target)
            binding.check(api)
            binding.check(api)
        result = {'matched':True, 'reason':'terminal_data_folder_account_match'}
    except Exception:
        result = {'matched':False, 'reason':'binding_or_attachment_unconfirmed'}
    finally:
        if attempted and api is not None:
            try:
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):api.shutdown()
            except Exception:pass
        if target is not None:target.close()
    return result


def main():
    parser = argparse.ArgumentParser(description='注文しない専用端末照合。設定値を出力しません。')
    parser.add_argument('--terminal-binding', default='terminal.local.json')
    parser.add_argument('--attach-running', action='store_true')
    parser.add_argument('--terminal-pid',type=int)
    args = parser.parse_args()
    try:
        spec = TerminalSpec.load(args.terminal_binding)
        report = run(spec,args.attach_running,args.terminal_pid)
    except Exception:
        report = {'matched':False,'reason':'local_binding_invalid'}
    print(json.dumps(report))
    return 0 if report['matched'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
