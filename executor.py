import MetaTrader5 as mt5
import numpy as np
import time

# --- 執行・監視クラス ---
class GridManager:
    def __init__(self, state, symbol="XAUUSD", volume=0.02, half_close_dist=10.0):
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

    def send_discord_message(self, text):
        import os
        import urllib.request
        import json

        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            print("[Warning] DISCORD_WEBHOOK_URL が設定されていないため、Discord通知をスキップします。")
            return

        payload = {"content": text}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as res:
                pass
        except Exception as e:
            print(f"[Error] Discord通知の送信に失敗しました: {e}")

    def place_grid_orders(self):
        # ゾーン内に5つの指値を配置 (STOP注文が必要な場合はエラーとして処理を中止)
        min_p = self.state.min_price
        max_p = self.state.max_price
        steps = [min_p + (max_p - min_p) * i / 4 for i in range(5)]

        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            err_msg = f"❌ [Error] ティック情報の取得に失敗したため、グリッド注文を配置できませんでした"
            print(err_msg)
            self.send_discord_message(f"🔔 **{self.symbol} グリッド注文結果**\n{err_msg}")
            return

        is_buy = (self.state.direction == "buy")
        direction_str = "買い (BUY)" if is_buy else "売り (SELL)"

        # STOP注文（逆指値）の発生有無を事前チェック
        has_stop_order = False
        invalid_prices = []
        for price in steps:
            price_r = round(price, 2)
            if is_buy:
                # 買いの場合、グリッド価格が現在のAsk以上であればBUY_STOPが必要になるためエラー
                if price_r >= tick.ask:
                    has_stop_order = True
                    invalid_prices.append(f"{price_r} (>= Ask: {tick.ask})")
            else:
                # 売りの場合、グリッド価格が現在のBid以下であればSELL_STOPが必要になるためエラー
                if price_r <= tick.bid:
                    has_stop_order = True
                    invalid_prices.append(f"{price_r} (<= Bid: {tick.bid})")

        if has_stop_order:
            err_msg = (
                f"❌ [Error] 逆指値（STOP）注文が必要な価格が含まれているため、発注を中止しました。\n"
                f"・方向: {direction_str}\n"
                f"・現在価格: Ask={tick.ask:.2f}, Bid={tick.bid:.2f}\n"
                f"・対象外の価格: {', '.join(invalid_prices)}"
            )
            print(err_msg)
            self.send_discord_message(f"🔔 **{self.symbol} グリッド注文エラー**\n{err_msg}")
            return

        order_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT
        order_type_str = "BUY LIMIT" if is_buy else "SELL LIMIT"

        success_count = 0
        details = []
        for price in steps:
            price_r = round(price, 2)
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": self.symbol,
                "volume": self.volume,
                "type": order_type,
                "price": price_r,
                "magic": 123456,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result is None:
                err_msg = f"注文送信失敗 (結果が返されませんでした): 価格 {price_r} ({order_type_str})"
                print(err_msg)
                details.append(f"❌ 価格 {price_r} ({order_type_str}): 失敗 (No Response)")
            elif result.retcode != mt5.TRADE_RETCODE_DONE:
                err_msg = f"注文送信失敗: 価格 {price_r} ({order_type_str}), retcode={result.retcode}"
                print(err_msg)
                details.append(f"❌ 価格 {price_r} ({order_type_str}): 失敗 (retcode={result.retcode})")
            else:
                success_count += 1
                details.append(f"✅ 価格 {price_r} ({order_type_str}): 成功 (ticket={getattr(result, 'order', 'N/A')})")

        if success_count == len(steps):
            summary = f"グリッド注文配置完了 ({direction_str}): {min_p} - {max_p}"
        else:
            summary = f"グリッド注文配置完了（一部または全て失敗）: 成功 {success_count}/{len(steps)} ({direction_str}): {min_p} - {max_p}"
        
        print(summary)

        # Discord通知メッセージ構築
        discord_text = (
            f"🔔 **{self.symbol} グリッド注文結果**\n"
            f"・方向: {direction_str}\n"
            f"・ゾーン: {min_p} - {max_p}\n"
            f"・現在価格: Ask={tick.ask:.2f}, Bid={tick.bid:.2f}\n"
            f"・結果: {summary}\n"
            f"・詳細:\n" + "\n".join(details)
        )
        self.send_discord_message(discord_text)


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

