import threading

# --- 状態管理クラス ---
class GridState:
    def __init__(self):
        self.min_price = 0.0
        self.max_price = 0.0
        self.is_new_request = False
        self.lock = threading.Lock()

    def update_zone(self, min_p, max_p):
        with self.lock:
            self.min_price = min_p
            self.max_price = max_p
            self.is_new_request = True
