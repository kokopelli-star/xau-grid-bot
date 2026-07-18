import MetaTrader5 as mt5
import numpy as np
import time

# --- 執行・監視クラス ---
class GridManager:
    def __init__(self, state, symbol="XAUUSD", volume=0.01, half_close_dist=10.0):
        self.state = state
        self.symbol = symbol
        self.volume = volume
        self.atr_period = 14  # ATRの計算期間
        self.atr_multiplier = 0.5 # バッファ倍率（まずは0.5で設定）
        self.half_close_dist = half_close_dist
        self.half_close_done = False

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
        # ゾーン内に5つの指値を配置 (buy/sellに応じて注文タイプを変更)
        min_p = self.state.min_price
        max_p = self.state.max_price
        steps = [min_p + (max_p - min_p) * i / 4 for i in range(5)]

        is_buy = (self.state.direction == "buy")
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT

        for price in steps:
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": self.symbol,
                "volume": self.volume,
                "type": order_type,
                "price": round(price, 2),
                "magic": 123456,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            mt5.order_send(request)
        print(f"グリッド注文配置完了 ({'買い' if is_buy else '売り'}): {min_p} - {max_p}")


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

    def handle_breakout_exit(self, is_buy):
        # 1. 未約定の注文（指値）を全てキャンセル
        orders = mt5.orders_get(symbol=self.symbol)
        if orders:
            for order in orders:
                mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket})
            print("未約定の指値注文をすべてキャンセルしました")

        # 2. ポジション取得
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            print("ポジションがありません。指値のキャンセルのみ完了しました。")
            return

        # 3. 最も建値の良いポジションを特定（買いは最低価格、売りは最高価格）
        if is_buy:
            best_pos = min(positions, key=lambda p: p.price_open)
        else:
            best_pos = max(positions, key=lambda p: p.price_open)
        print(f"最良建値ポジションを特定 ({'買い' if is_buy else '売り'}): ticket={best_pos.ticket}, price_open={best_pos.price_open}")

        # 4. 最良ポジション以外（建値の悪いもの）を全決済
        for pos in positions:
            if pos.ticket == best_pos.ticket:
                continue

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
                "comment": "grid profit exit",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"建値の悪いポジションをクローズしました: ticket={pos.ticket}, price_open={pos.price_open}")
            else:
                print(f"ポジションクローズ失敗: ticket={pos.ticket}, retcode={result.retcode}")

        # 5. 残した最良ポジションのストップロス（SL）を建値に変更してリスクフリーにする
        sl_request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": best_pos.ticket,
            "symbol": self.symbol,
            "sl": round(best_pos.price_open, 2),  # 建値に変更
            "tp": 0.0                             # 0.0 はTPなし
        }
        result = mt5.order_send(sl_request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"最良ポジション {best_pos.ticket} の逆指値(SL)を建値 {best_pos.price_open} に設定しました (リスクフリー化完了)")
        else:
            print(f"最良ポジションの逆指値設定に失敗しました: ticket={best_pos.ticket}, retcode={result.retcode}")

    def check_and_execute_half_close(self, current_price):
        if self.half_close_done:
            return

        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return

        is_buy = (self.state.direction == "buy")
        
        if is_buy:
            best_pos = min(positions, key=lambda p: p.price_open)
            profit_pips = current_price - best_pos.price_open
        else:
            best_pos = max(positions, key=lambda p: p.price_open)
            profit_pips = best_pos.price_open - current_price

        if profit_pips >= self.half_close_dist:
            print(f"部分利確トリガー検知 (利益幅: {profit_pips:.2f} >= 設定幅: {self.half_close_dist})")
            
            for pos in positions:
                half_vol = round(pos.volume / 2, 2)
                if half_vol < 0.01:
                    continue
                
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "volume": half_vol,
                    "type": close_type,
                    "position": pos.ticket,
                    "price": current_price,
                    "deviation": 20,
                    "magic": 123456,
                    "comment": "grid half close",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"ポジション {pos.ticket} を半分決済しました (ロット: {pos.volume} -> {half_vol})")
                else:
                    print(f"半分決済失敗: ticket={pos.ticket}, retcode={result.retcode}")
                    
            self.half_close_done = True

    def run_executor(self):
        while True:
            if self.state.is_new_request:
                self.close_all_positions()
                self.place_grid_orders()
                self.half_close_done = False
                self.state.is_new_request = False
            time.sleep(1)

    def run_monitor(self):
        print("監視ループ開始...")
        while True:
            # ゾーンが設定されており、かつ新規配置リクエストの処理が完了している場合のみ監視
            if self.state.min_price > 0 and not self.state.is_new_request:
                tick = mt5.symbol_info_tick(self.symbol)

                if tick:
                    current_price = tick.bid
                    self.check_and_execute_half_close(current_price)
                    atr = self.get_atr()
                    buffer = atr * self.atr_multiplier
                    is_buy = (self.state.direction == "buy")

                    # 1. ゾーン下限の逸脱判定
                    if current_price < (self.state.min_price - buffer):
                        if is_buy:
                            # 買いグリッドの場合：下限割れは「損切り」
                            print(f"ゾーン下限逸脱（買い損切り）検知! (Price: {current_price}, ATR: {atr:.2f})")
                            self.close_all_positions()
                        else:
                            # 売りグリッドの場合：下限割れは「利確」
                            print(f"ゾーン下限逸脱（売り利確）検知! (Price: {current_price}, ATR: {atr:.2f})")
                            self.handle_breakout_exit(is_buy=False)
                        self.state.min_price = 0.0 # 監視終了
                    
                    # 2. ゾーン上限の逸脱判定
                    elif current_price > (self.state.max_price + buffer):
                        if is_buy:
                            # 買いグリッドの場合：上限突破は「利確」
                            print(f"ゾーン上限逸脱（買い利確）検知! (Price: {current_price}, ATR: {atr:.2f})")
                            self.handle_breakout_exit(is_buy=True)
                        else:
                            # 売りグリッドの場合：上限突破は「損切り」
                            print(f"ゾーン上限逸脱（売り損切り）検知! (Price: {current_price}, ATR: {atr:.2f})")
                            self.close_all_positions()
                        self.state.min_price = 0.0 # 監視終了

            time.sleep(1)

