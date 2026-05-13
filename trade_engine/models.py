from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, List


@dataclass
class Leg:
    action:      Literal["buy", "sell"]
    right:       Literal["CE", "PE"]
    strike:      int
    expiry:      date
    symbol:      str
    quantity:    int
    entry_price: float = 0.0
    order_id:    str   = ""


@dataclass
class Position:
    legs:       List[Leg]
    net_credit: float       # total premium collected (positive = we received cash)
    max_risk:   float       # maximum possible loss
    max_profit: float       # = net_credit for credit spreads
    strategy:   str
    entry_time: datetime = field(default_factory=datetime.now)
    is_open:    bool     = True
