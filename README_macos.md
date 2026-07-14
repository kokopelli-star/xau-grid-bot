# macOSでの実行・開発手順

macOS環境で本プロジェクト（xau-grid-bot）を実行およびテストするための手順です。

## 概要

`MetaTrader5`（MT5）の公式PythonライブラリはWindows専用であるため、macOSではそのまま実行できません。
本手順では、ローカル開発および動作テスト用として**MT5のダミー（Mock）モジュール**を作成し、FastAPIサーバーおよび監視ロジックを起動する方法を説明します。

---

## 1. 依存関係のインストール

Apple Silicon (M1/M2/M3など) のmacOS環境でアーキテクチャの不整合を防ぐため、`arch -arm64` を指定してネイティブビルドでインストールします。

```bash
arch -arm64 python3 -m pip install --force-reinstall fastapi uvicorn numpy
```

---

## 2. MetaTrader5ダミーモジュールの配置

Pythonはカレントディレクトリから優先してモジュールをインポートするため、プロジェクトのルートディレクトリに `MetaTrader5.py` という名前でダミーの定義ファイルを作成します。

このファイル（`MetaTrader5.py`）には以下の内容が含まれています：
- MT5の各種定数（`TIMEFRAME_M15`, `TRADE_ACTION_PENDING` など）
- 注文(`order_send`)やポジション・レート取得などのモック関数（注文リクエストを検知して標準出力にログ表示する仕組み）

---

## 3. アプリケーションの起動

ログ出力をリアルタイムで確認しやすくするために、Pythonのバッファリングを無効化する `-u` オプションと、`arch -arm64` を使用して `main.py` を起動します。

```bash
arch -arm64 python3 -u main.py
```

起動に成功すると、以下のようなログが表示され、ポート `8000` でWebhook受付サーバーが待機状態になります。

```text
[Mock MT5] MT5 Initialized successfully.
監視ループ開始...
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

---

## 4. 動作テスト（Webhook送信）

起動したサーバーに対して、別のターミナルから `curl` コマンドで擬似的なWebhookリクエストを送信することで、グリッド注文の生成ロジックをテストできます。

### リクエスト例
```bash
curl -X POST -H "Content-Type: application/json" -d '{"min": 2340.0, "max": 2360.0}' http://localhost:8000/webhook
```

### レスポンス
```json
{"status":"received","zone":[2340.0,2360.0]}
```

### サーバー側のログ変化
リクエスト受信後、指定したレンジ（例: 2340.0〜2360.0）を5等分したグリッド注文（買い指値）がモック上で正しく配置されたことを示すログが出力されます。

```text
INFO:     127.0.0.1:xxxxx - "POST /webhook HTTP/1.1" 200 OK
[Mock MT5] order_send: request={'action': 5, 'symbol': 'XAUUSD', 'volume': 0.01, 'type': 2, 'price': 2340.0, 'magic': 123456, 'type_filling': 1}
[Mock MT5] Placed pending order: ticket=1000, price=2340.0
...
[Mock MT5] Placed pending order: ticket=1004, price=2360.0
グリッド注文配置完了: 2340.0 - 2360.0
```
