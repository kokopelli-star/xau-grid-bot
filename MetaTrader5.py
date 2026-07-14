import numpy as np

# --- MetaTrader5 Dummy Mock for macOS ---

TIMEFRAME_M15 = 15
TRADE_ACTION_PENDING = 5
ORDER_TYPE_BUY_LIMIT = 2
ORDER_FILLING_IOC = 1
ORDER_TYPE_SELL = 1
POSITION_TYPE_BUY = 0
ORDER_TYPE_BUY = 0
TRADE_ACTION_REMOVE = 8
TRADE_ACTION_DEAL = 1
ORDER_TIME_GTC = 0
TRADE_RETCODE_DONE = 10009

class Tick:
    def __init__(self, bid=2350.0, ask=2350.5):
        self.bid = bid
        self.ask = ask

class Order:
    def __init__(self, ticket, symbol, type, price, volume):
        self.ticket = ticket
        self.symbol = symbol
        self.type = type
        self.price = price
        self.volume = volume

class Position:
    def __init__(self, ticket, symbol, type, volume):
        self.ticket = ticket
        self.symbol = symbol
        self.type = type
        self.volume = volume

_orders = []
_positions = []
_ticket_counter = 1000

def initialize():
    print("[Mock MT5] MT5 Initialized successfully.")
    return True

def shutdown():
    print("[Mock MT5] MT5 Shutdown.")
    return True

def symbol_info_tick(symbol):
    # Default mock price around 2350.0
    return Tick()

def orders_get(symbol=None):
    if symbol:
        return [o for o in _orders if o.symbol == symbol]
    return list(_orders)

def positions_get(symbol=None):
    if symbol:
        return [p for p in _positions if p.symbol == symbol]
    return list(_positions)

class OrderResult:
    def __init__(self, retcode=TRADE_RETCODE_DONE):
        self.retcode = retcode

def order_send(request):
    global _ticket_counter, _orders, _positions
    action = request.get("action")
    print(f"[Mock MT5] order_send: request={request}")
    if action == TRADE_ACTION_PENDING:
        ticket = _ticket_counter
        _ticket_counter += 1
        new_order = Order(
            ticket=ticket,
            symbol=request.get("symbol"),
            type=request.get("type"),
            price=request.get("price"),
            volume=request.get("volume")
        )
        _orders.append(new_order)
        print(f"[Mock MT5] Placed pending order: ticket={ticket}, price={new_order.price}")
    elif action == TRADE_ACTION_REMOVE:
        order_ticket = request.get("order")
        _orders = [o for o in _orders if o.ticket != order_ticket]
        print(f"[Mock MT5] Removed pending order: ticket={order_ticket}")
    elif action == TRADE_ACTION_DEAL:
        # Simulate execution/closure
        pos_ticket = request.get("position")
        _positions = [p for p in _positions if p.ticket != pos_ticket]
        print(f"[Mock MT5] Position closed: ticket={pos_ticket}")
    return OrderResult(TRADE_RETCODE_DONE)

def copy_rates_from_pos(symbol, timeframe, start_pos, count):
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
    rates['high'] = [2350.0 + i * 0.1 for i in range(count)]
    rates['low'] = [2349.0 + i * 0.1 for i in range(count)]
    rates['close'] = [2349.5 + i * 0.1 for i in range(count)]
    return rates
