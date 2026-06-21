from fastapi import FastAPI
import uvicorn

# --- Webhook受信サーバー ---
class TradingServer:
    def __init__(self, state):
        self.app = FastAPI()
        self.state = state
        self.app.post("/webhook")(self.webhook)

    async def webhook(self, data: dict):
        self.state.update_zone(data["min"], data["max"])
        return {"status": "received", "zone": [data["min"], data["max"]]}

    def run(self):
        uvicorn.run(self.app, host="0.0.0.0", port=8000)
