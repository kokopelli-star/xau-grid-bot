import MetaTrader5 as mt5
import numpy as np
import time

# --- 執行・監視クラス ---
class GridManager:
    def __init__(self, state, symbol="XAUUSD", volume=0.01):
        self.state = state
        self.symbol = symbol
        self.volume = volume
        self.atr_period = 14  # ATRの計算期間
        self.atr_multiplier = 0.5 # バッファ倍率（まずは0.5で設定）

    def get_atr(self):
        # 15分足のデータを取得 (期間+1本分)
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M15, 0, self.atr_period + 1)
        if rates is None or len(rates) < self.atr_period + 1:
            return 0.0

        high = rates['high']
        low = rates['low']
        close = rates['close']

        # True Range の計算
        tr = np.maximum(high[1:] - low[1:],
                        np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))

        # ATR (単純移動平均)
        return np.mean(tr)

    def place_grid_orders(self):
        # ゾーン内に5つの買い指値を配置
        min_p = self.state.min_price
        max_p = self.state.max_price
        steps = [min_p + (max_p - min_p) * i / 4 for i in range(5)]

        for price in steps:
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": self.symbol,
                "volume": self.volume,
                "type": mt5.ORDER_TYPE_BUY_LIMIT,
                "price": round(price, 2),
                "magic": 123456,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            mt5.order_send(request)
        print(f"グリッド注文配置完了: {min_p} - {max_p}")

    def close_all_positions(self):
        # 保有ポジションと指値を全決済・全キャンセル
        orders = mt5.orders_get(symbol=self.symbol)
        if orders:
            for order in orders:
                mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket})

        positions = mt5.positions_get(symbol=self.symbol)
        if positions:
            for pos in positions:
                tick = mt5.symbol_info_tick(self.symbol)
                if tick is None:
                    print(f"ティック情報の取得に失敗したため、ポジション {pos.ticket} をクローズできません")
                    continue
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "volume": pos.volume,
                    "type": close_type,
                    "position": pos.ticket,
                    "price": price,
                    "deviation": 20,
                    "magic": 123456,
                    "comment": "grid close all",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(request)
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    print(f"ポジションクローズ失敗: ticket={pos.ticket}, retcode={result.retcode}")
        print("全ポジション・注文をクリアしました")

    def run_executor(self):
        while True:
            if self.state.is_new_request:
                self.close_all_positions()
                self.place_grid_orders()
                self.state.is_new_request = False
            time.sleep(1)

    def run_monitor(self):
        print("監視ループ開始...")
        while True:
            # ゾーンが設定されている場合のみ監視
            if self.state.min_price > 0:
                tick = mt5.symbol_info_tick(self.symbol)
                if tick:
                    current_price = tick.bid
                    atr = self.get_atr()
                    buffer = atr * self.atr_multiplier

                    # 損切り判定: ゾーン外 + ATRバッファ
                    if current_price > (self.state.max_price + buffer) or \
                       current_price < (self.state.min_price - buffer):
                        print(f"ゾーン逸脱検知! (Price: {current_price}, ATR: {atr:.2f})")
                        self.close_all_positions()
                        self.state.min_price = 0.0 # 監視終了
            time.sleep(1)
