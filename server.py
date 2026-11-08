import hmac
import math
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException
import uvicorn

MIN_TOKEN_LENGTH = 32


class TokenError(RuntimeError):
    pass


def load_token(path):
    """Read the shared webhook secret from a local, gitignored file."""
    try:
        token = Path(path).read_text(encoding='utf-8').strip()
    except OSError:
        raise TokenError('Webhookトークンファイルを読めません。') from None
    # URL-safe characters only, so the token can be embedded in Pine's JSON string as-is.
    if not re.fullmatch(r'[A-Za-z0-9_-]{%d,}' % MIN_TOKEN_LENGTH, token):
        raise TokenError(f'Webhookトークンは英数字・_・-のみで{MIN_TOKEN_LENGTH}文字以上にしてください。')
    return token


# --- Webhook受信サーバー ---
class TradingServer:
    def __init__(self, state, token):
        if not token:
            raise TokenError('Webhookトークンが未設定です。')
        self.app = FastAPI()
        self.state = state
        self.token = token.encode('utf-8')
        self.app.post("/webhook")(self.webhook)

    async def webhook(self, data: dict):
        # TradingView cannot send custom headers, so the secret travels in the body.
        supplied = data.get("token")
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied.encode('utf-8'), self.token):
            print("[Webhook Rejected] 認証失敗")
            raise HTTPException(status_code=401, detail="unauthorized")
        payload = {k: v for k, v in data.items() if k != "token"}
        print(f"[Webhook Received] POST data: {payload}")
        try:
            min_p = float(payload["min"])
            max_p = float(payload["max"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="min/max required") from None
        if not (math.isfinite(min_p) and math.isfinite(max_p)):
            raise HTTPException(status_code=400, detail="min/max must be finite")
        direction = str(payload.get("direction", "buy")).lower()
        if direction not in ["buy", "sell"]:
            direction = "buy"
        self.state.update_zone(min_p, max_p, direction)
        return {
            "status": "received",
            "direction": direction,
            "zone": [min_p, max_p]
        }


    def run(self):
        # Loopback only: public ingress (Tailscale Funnel) proxies to 127.0.0.1.
        uvicorn.run(self.app, host="127.0.0.1", port=8000, ws="none")
