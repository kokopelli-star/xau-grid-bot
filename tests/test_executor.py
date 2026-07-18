import unittest
from unittest.mock import patch, MagicMock
import numpy as np
from state import GridState
from executor import GridManager

class TestGridManager(unittest.TestCase):
    def setUp(self):
        # テスト用の状態管理オブジェクトを作成
        self.state = GridState()
        # 買いグリッドのゾーンを設定 (2340.0 〜 2360.0)
        self.state.update_zone(2340.0, 2360.0, "buy")
        self.state.is_new_request = False
        
        # GridManagerを初期化
        self.manager = GridManager(self.state, symbol="XAUUSD", volume=0.02, half_close_dist=10.0)

    def _get_mock_rates(self, count, high_val, low_val, close_val):
        """ATR計算用のモックデータを生成するヘルパー関数"""
        dtype = [
            ('time', 'i8'),
            ('open', 'f8'),
            ('high', 'f8'),
            ('low', 'f8'),
            ('close', 'f8'),
            ('tick_volume', 'i8'),
            ('spread', 'i8'),
            ('real_volume', 'i8')
        ]
        rates = np.zeros(count, dtype=dtype)
        rates['high'] = high_val
        rates['low'] = low_val
        rates['close'] = close_val
        return rates

    @patch('executor.mt5')
    def test_check_and_execute_half_close_not_triggered(self, mock_mt5):
        """利益幅が設定幅（10.0）に達していない場合は部分利確を実行しない"""
        # 建値 2340.0 のポジションが存在する状態をモック化
        mock_position = MagicMock()
        mock_position.ticket = 5001
        mock_position.volume = 0.02
        mock_position.price_open = 2340.0
        mock_position.type = 0 # POSITION_TYPE_BUY
        
        mock_mt5.positions_get.return_value = [mock_position]
        
        # 現在価格 2349.0 (利益 9.0 < 10.0)
        self.manager.check_and_execute_half_close(2349.0)
        
        # 決済注文が送信されていないこと
        mock_mt5.order_send.assert_not_called()
        self.assertFalse(self.manager.half_close_done)

    @patch('executor.mt5')
    def test_check_and_execute_half_close_triggered(self, mock_mt5):
        """利益幅が設定幅（10.0）に達した場合に部分利確を実行し、フラグを更新する"""
        mock_position = MagicMock()
        mock_position.ticket = 5001
        mock_position.volume = 0.02
        mock_position.price_open = 2340.0
        mock_position.type = 0 # POSITION_TYPE_BUY
        
        mock_mt5.positions_get.return_value = [mock_position]
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.order_send.return_value.retcode = 10009

        # 現在価格 2350.0 (利益 10.0 >= 10.0)
        self.manager.check_and_execute_half_close(2350.0)
        
        # 決済注文が1度送信されたこと
        mock_mt5.order_send.assert_called_once()
        self.assertTrue(self.manager.half_close_done)
        
        # 元ロットの半分(0.01)でクローズされていることを検証
        sent_request = mock_mt5.order_send.call_args[0][0]
        self.assertEqual(sent_request["action"], 1) # TRADE_ACTION_DEAL
        self.assertEqual(sent_request["volume"], 0.01)
        self.assertEqual(sent_request["position"], 5001)

    @patch('executor.time.sleep', side_effect=InterruptedError("Loop exit"))
    @patch('executor.mt5')
    def test_run_monitor_breakout_exit_buy_profit(self, mock_mt5, mock_sleep):
        """買いグリッドにてゾーン上限（max_price + buffer）を突破した際、利確処理（最良ポジ以外を決済＆SL建値化）を行うこと"""
        # 最良ポジションとそれ以外のポジションを用意
        pos_best = MagicMock()
        pos_best.ticket = 5001
        pos_best.volume = 0.02
        pos_best.price_open = 2340.0
        pos_best.type = 0 # POSITION_TYPE_BUY

        pos_worst = MagicMock()
        pos_worst.ticket = 5002
        pos_worst.volume = 0.02
        pos_worst.price_open = 2350.0
        pos_worst.type = 0 # POSITION_TYPE_BUY

        mock_mt5.positions_get.return_value = [pos_best, pos_worst]
        mock_mt5.orders_get.return_value = []
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.order_send.return_value.retcode = 10009
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.TRADE_ACTION_SLTP = 6

        # ATR = 10.0 のダミーデータ (buffer = ATR * 0.5 = 5.0)
        # 上限 2360.0 + 5.0 = 2365.0
        mock_mt5.copy_rates_from_pos.return_value = self._get_mock_rates(15, 2355.0, 2345.0, 2350.0)

        # 現在価格が上限を超える 2366.0 の場合
        tick = MagicMock()
        tick.bid = 2366.0
        tick.ask = 2366.5
        mock_mt5.symbol_info_tick.return_value = tick

        # ハーフクローズ済み状態にして、余分なクローズ注文を抑制
        self.manager.half_close_done = True

        # ループを抜ける例外を受け取る前提で run_monitor を実行
        with self.assertRaises(InterruptedError):
            self.manager.run_monitor()

        # 1. 最良建値以外のポジション（pos_worst: 5002）が決済されていること
        # order_sendの呼び出し履歴をチェック
        calls = mock_mt5.order_send.call_args_list
        
        # 決済注文（pos_worstのクローズ）の検証
        close_call = [c for c in calls if c[0][0].get("action") == mock_mt5.TRADE_ACTION_DEAL]
        self.assertEqual(len(close_call), 1)
        self.assertEqual(close_call[0][0][0]["position"], 5002)

        # 2. 最良ポジション（pos_best: 5001）のSLが建値に設定されていること
        sl_call = [c for c in calls if c[0][0].get("action") == mock_mt5.TRADE_ACTION_SLTP]
        self.assertEqual(len(sl_call), 1)
        self.assertEqual(sl_call[0][0][0]["position"], 5001)
        self.assertEqual(sl_call[0][0][0]["sl"], 2340.0)

        # 3. 監視が終了していること (min_price = 0.0)
        self.assertEqual(self.state.min_price, 0.0)

    @patch('executor.time.sleep', side_effect=InterruptedError("Loop exit"))
    @patch('executor.mt5')
    def test_run_monitor_breakout_exit_buy_loss(self, mock_mt5, mock_sleep):
        """買いグリッドにてゾーン下限（min_price - buffer）を割り込んだ際、全ポジションと注文をクローズ（損切り）すること"""
        pos = MagicMock()
        pos.ticket = 5001
        pos.volume = 0.02
        pos.price_open = 2340.0
        pos.type = 0 # POSITION_TYPE_BUY

        mock_mt5.positions_get.return_value = [pos]
        
        # 未約定の指値注文
        order = MagicMock()
        order.ticket = 1001
        mock_mt5.orders_get.return_value = [order]
        
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.order_send.return_value.retcode = 10009
        mock_mt5.TRADE_ACTION_REMOVE = 8
        mock_mt5.TRADE_ACTION_DEAL = 1

        # ATR = 10.0 (buffer = ATR * 0.5 = 5.0)
        # 下限 2340.0 - 5.0 = 2335.0
        mock_mt5.copy_rates_from_pos.return_value = self._get_mock_rates(15, 2355.0, 2345.0, 2350.0)

        # 現在価格が下限を下回る 2334.0 の場合
        tick = MagicMock()
        tick.bid = 2334.0
        tick.ask = 2334.5
        mock_mt5.symbol_info_tick.return_value = tick

        # ハーフクローズ済み状態にする
        self.manager.half_close_done = True

        with self.assertRaises(InterruptedError):
            self.manager.run_monitor()

        # 注文削除(TRADE_ACTION_REMOVE)とポジションクローズ(TRADE_ACTION_DEAL)が送られていること
        calls = mock_mt5.order_send.call_args_list
        
        # 指値キャンセル
        remove_calls = [c for c in calls if c[0][0].get("action") == mock_mt5.TRADE_ACTION_REMOVE]
        self.assertEqual(len(remove_calls), 1)
        self.assertEqual(remove_calls[0][0][0]["order"], 1001)

        # ポジションクローズ
        close_calls = [c for c in calls if c[0][0].get("action") == mock_mt5.TRADE_ACTION_DEAL]
        self.assertEqual(len(close_calls), 1)
        self.assertEqual(close_calls[0][0][0]["position"], 5001)

        # 監視が終了していること
        self.assertEqual(self.state.min_price, 0.0)

if __name__ == '__main__':
    unittest.main()
