# xau-grid-bot

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

### 3. ngrokを使用したWebhook受信用トンネリングの設定
TradingViewなどの外部サービスからローカルのサーバーにリクエストを転送するために、`ngrok` で接続用のURLを固定（ドメイン指定）して起動します。

```bash
ngrok http --domain=awaited-oddly-squid.ngrok-free.app 8000
```

> [!TIP]
> ngrokで固定ドメインを発行・設定する方法については、以下の解説記事などを参考にしてください。
> - [【簡単】ngrokで発行されるURLを固定する (Zenn)](https://zenn.dev/y_taiki/articles/ngrok_domain)

### 4. アプリケーションの起動
別のコマンドプロンプト（またはPowerShell）を起動し、以下のコマンドでボットのメインプロセスを実行します。

```bash
py .\main.py
```

実行すると、FastAPIサーバーが `8000` 番ポートで待機を開始し、同時に価格とポジションの監視ループが動作し始めます。

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