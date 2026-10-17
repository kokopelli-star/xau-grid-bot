"""Fixed existing-terminal startup. Importing this module never initializes MT5."""
import argparse
import sys
import threading
from state import GridState
from executor import GridManager
from server import TradingServer
from terminal_binding import TerminalSpec, TerminalBinding, BindingError
from terminal_process import find_running_terminal
import MetaTrader5 as mt5


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--terminal-binding', default='terminal.local.json')
    args = parser.parse_args()
    target = None
    attempted = False
    binding = None
    try:
        spec = TerminalSpec.load(args.terminal_binding)
        if sys.platform != 'win32':
            raise BindingError('Windows専用。接続しません。')
        target = find_running_terminal(expected_path=spec.exe)
        if not target.alive(): raise BindingError('対象端末が終了しています。')
        binding = TerminalBinding(spec, target)
        attempted = True
        if not mt5.initialize(spec.exe, timeout=10000):
            raise BindingError('対象端末への接続失敗。')
        binding.check(mt5, trading=True)
        state = GridState()
        server = TradingServer(state)
        manager = GridManager(state, binding=binding)
        # Worker exceptions latch the shared guard. The monitoring loop sees the
        # latch even when there is no zone, so another worker cannot keep trading.
        def executor():
            try:
                manager.run_executor()
            except Exception:
                binding.stop()
                print('執行停止。端末・口座と未確定注文の確認が必要です。')
        threading.Thread(target=server.run, daemon=True).start()
        worker = threading.Thread(target=executor, daemon=True)
        worker.start()
        try:
            manager.run_monitor()
        finally:
            binding.stop()
            worker.join()
    except (Exception, KeyboardInterrupt):
        if binding is not None: binding.stop()
        print('起動・売買処理停止。ローカル設定、専用端末、未確定注文を確認してください。')
        return 1
    finally:
        if attempted: mt5.shutdown()
        if target is not None: target.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
