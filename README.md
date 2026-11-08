# xau-grid-bot

**専用端末固定の変更案：[ローカル設定・停止条件・注文なし診断](TERMINAL_BINDING.md)**。VPS適用・再起動は未承認。既存起動コマンドにも `terminal.local.json` が必須になります。

TradingViewなどからのWebhookリクエストをトリガーにして、MetaTrader 5 (MT5) と連動し、XAUUSD（ゴールド）のグリッドトレードを自動実行するPythonボットです。

---

## Windows環境での実行・起動手順

実際のMT5取引環境と連携して自動トレードを行うための手順です。

### 1. 事前準備 (MT5の設定)
1. Windows上で **MetaTrader 5 (MT5)** を起動し、取引を行う証券会社の口座にログインします。
2. MT5のメニューから **「ツール」 > 「オプション」** を開きます。
3. **「エキスパートアドバイザ」** タブを選択し、**「アルゴリズム取引を許可する」** にチェックを入れて「OK」をクリックします。

### 2. 依存関係のインストール
コマンドプロンプトまたはPowerShellを開き、プロジェクトのルートディレクトリで以下のコマンドを実行してライブラリをインストールします。

```bash
pip install -r requirements.txt
```

### 3. Webhookトークンの作成
`/webhook` はトークンが一致しないリクエストを `401` で拒否します。TradingViewはカスタムヘッダーを送れないため、トークンはJSON本文の `token` フィールドで送ります。

プロジェクトのルートで以下を実行し、`webhook.local.token`（gitignore対象）を作成します。英数字・`_`・`-` のみ、32文字以上が必要です。ファイルが無い・形式が不正な場合、MT5に接続する前に起動を中止します。

```powershell
py -c "import secrets; open('webhook.local.token','w').write(secrets.token_urlsafe(32))"
```

TradingViewでは `[kt] ZigZag Break Target` の設定 **「Webhook token」** にこのファイルと同じ値を入力し、アラートを作成し直します（アラートは作成時点の入力値を保持するため）。トークンをチャット・リポジトリ・スクリーンショットに残さないでください。漏えい時はファイルを作り直し、ボット再起動とアラート再作成を行います。

### 4. Tailscale FunnelによるWebhook受信の公開
サーバーは `127.0.0.1:8000` だけで待ち受けます。インターネットからの受信はTailscale Funnelで中継します（ngrokの固定ドメインは別ボットが使用中のため使いません）。

```powershell
tailscale funnel --bg 8000
```

TradingViewのWebhook URLは `https://<マシン名>.<tailnet名>.ts.net/webhook` です。`tailscale funnel status` で設定を確認、`tailscale funnel --https=443 off` で公開を停止できます。

### 5. アプリケーションの起動
別のPowerShellを起動し、以下のコマンドでボットのメインプロセスを実行します。

```powershell
py .\main.py
```

`--terminal-binding`（既定 `terminal.local.json`）と `--webhook-token`（既定 `webhook.local.token`）でファイルの場所を変更できます。実行すると、FastAPIサーバーが `127.0.0.1:8000` で待機を開始し、同時に価格とポジションの監視ループが動作し始めます。

---

## Discord通知の設定 (任意)

新規にグリッド注文が配置された際、注文結果のサマリーと成否（OK/NG）の詳細をDiscordへ自動通知させることができます。

### 1. Discord Webhook URL の取得
1. 通知を受け取りたいDiscordサーバーのテキストチャンネルの「チャンネル編集」（歯車アイコン）を開きます。
2. **「連携サービス」** メニューを選択し、**「ウェブフック」** をクリックします。
3. **「新しいウェブフック」** を作成し、作成されたWebhookの設定から **「ウェブフックURLをコピー」** をクリックしてURLを取得します。

### 2. 環境変数の設定と起動
起動するシェルに合わせて、環境変数 `DISCORD_WEBHOOK_URL` を設定した上でボットを起動します。

- **Windows (PowerShell)**:
  ```powershell
  $env:DISCORD_WEBHOOK_URL="取得したWebhook URL"
  py .\main.py
  ```
- **Windows (コマンドプロンプト)**:
  ```cmd
  set DISCORD_WEBHOOK_URL=取得したWebhook URL
  py .\main.py
  ```
- **macOS / Linux**:
  ```bash
  export DISCORD_WEBHOOK_URL="取得したWebhook URL"
  arch -arm64 python3 main.py
  ```

---

## macOS環境での開発・テスト実行について

公式の `MetaTrader5` ライブラリはWindows専用のため、macOS上では実際のMT5と連動させることはできません。
macOS環境でダミーモジュール（モック）を使用して動作テストを行う手順については、[README_macos.md](file:///Users/ktarumi/Git/xau-grid-bot/README_macos.md) を参照してください。