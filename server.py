from fastapi import FastAPI
import uvicorn

# --- Webhook受信サーバー ---
class TradingServer:
    def __init__(self, state):
        self.app = FastAPI()
        self.state = state
        self.app.post("/webhook")(self.webhook)

    async def webhook(self, data: dict):
        direction = data.get("direction", "buy").lower()
        if direction not in ["buy", "sell"]:
            direction = "buy"
        self.state.update_zone(data["min"], data["max"], direction)
        return {
            "status": "received",
            "direction": direction,
            "zone": [data["min"], data["max"]]
        }


    def run(self):
        uvicorn.run(self.app, host="0.0.0.0", port=8000)
