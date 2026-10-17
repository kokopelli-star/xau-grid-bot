# 専用MT5接続先と口座の固定（未公開の変更案）

この変更はクラウドでのコード・模擬テストのみです。VPSへの適用、既存bot再起動、実MT5接続、ngrok変更、実注文は別承認です。HTTP `/webhook` の入力・応答、売買条件、symbol単位の処理範囲は変更していません。

## 設定はVPSローカルだけ

将来適用が承認された後、`terminal.example.json` を `terminal.local.json` として用意し、本人が以下を入力します。全nullのtemplateでは起動を拒否します。ファイルはgitignore対象で、共有・commitしません。

- `terminal_exe_path`：専用 `terminal64.exe` の絶対パス。
- `terminal_data_path`：専用端末の「ファイル→データフォルダを開く」で確認した絶対パス。
- `expected_account_login`：想定口座番号（整数）。
- `expected_account_server`：想定serverの完全一致文字列。

passwordやtokenは受け付けません。口座番号/serverは照合専用で、initialize/loginへ渡しません。既存ログインを手動で確認し、稼働中に切替えない運用が必要です。新botと旧botは別インストール・別data folder・別口座・別Python processとし、口座情報や端末データをコピーして使い回しません。`/portable`の切替や自動設定は実装しません。

将来の起動形式は `py main.py --terminal-binding terminal.local.json`。現在の `py main.py` も同じローカルファイルを必須として読みます。対象EXEの既存プロセスがなければ起動しません。同一EXEの候補が複数あれば拒否し、別端末へのfallbackはありません。

## 停止の意味

initializeへ固定EXEを渡し、接続後にinstallation / data folder / login / server / 接続を照合します。各売買処理・両workerループ・全7 native送信箇所（新規pending、決済、取消、部分決済、SL変更）を共通guardで確認。送信直前と送信後にも再確認し、切断、不一致、送信例外を検出したら共有guardが停止を保持します。片方workerの例外でももう片方から送信を続けません。自動再接続・自動login・別端末探索・自動復帰はありません。

送信後の異常は約定している可能性があるため結果不明です。再起動前に本人が注文・建玉・履歴を照合してください。旧botには永続注文台帳/自動復旧照合はなく、今回それを追加したわけではありません。停止は新たなAPI送信を止めるもので、既存pending取消や強制決済を意味しません。旧戦略のsymbol全体への決済/取消/半決済は維持しているため、**旧口座の同symbolの手動建玉や別EA建玉も対象になり得ます**。

## 注文なし診断（実行は別途本人確認後）

`py diagnose_terminal.py --terminal-binding terminal.local.json --attach-running --terminal-pid <対象PID>`

PIDは実プロセスIDに置換します。指定しない場合も固定EXEで候補を絞ります。同一EXE複数プロセスはPIDを指定しても拒否します。結果はmatched / reasonだけで、パス・口座番号・serverを出力しません。診断からexecutor/serverはimportせず、注文・order_check・login APIを呼びません。

## 限界と検証

MT5 initializeにatomic attach-only/PID APIはありません。事前検出後の終了競合で端末が起動する可能性、保存済み口座を利用する可能性が残ります。口座確認と送信も原子的ではなく、確認直後の手動切替を完全に防げません。送信後の不一致は停止し、結果不明として扱います。事前確認で検出できなかった切替→復帰も保証対象外です。

模擬テストのみ。Windows二端末実統合・実注文・実再起動は未検証。旧HEADの既存4テストは2件失敗を別ディレクトリで再現しました。戦略変更なしで、接触済み状態・確定足更新・価格/約定後の模擬状態・sleep条件のfixtureを補正しました。

`terminal_binding.py` と `terminal_process.py` は新botの同等モジュールと独立copyです。将来変更時は両方の模擬テストと差分レビューが必要です。

最終クラウド検証：`python -m unittest discover -s tests -v` **22件成功**（既存4件＋18件）。`python -m compileall -q main.py executor.py terminal_binding.py terminal_process.py diagnose_terminal.py tests`、`git diff --check` 成功。
独立レビューでNone/拒否結果判定と共有停止の並行競合を修正。判定まで同じRLockで保護し、barrierを使った別worker同時送信テストを追加しました。最終再レビューで追加重大指摘なし。
None・不明retcode・拒否結果でも追加batch送信を止めます。これは成功時の売買条件変更ではなく、結果不明/拒否時の停止条件の追加です。
