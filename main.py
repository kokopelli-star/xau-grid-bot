from state import GridState
from executor import GridManager
from server import TradingServer
import threading
import MetaTrader5 as mt5

if __name__ == "__main__":
    if not mt5.initialize():
        print("MT5初期化失敗")
        exit()

    state = GridState()
    server = TradingServer(state)
    manager = GridManager(state)

    threading.Thread(target=server.run, daemon=True).start()
    threading.Thread(target=manager.run_executor, daemon=True).start()

    # 監視ループをメインで実行
    manager.run_monitor()

