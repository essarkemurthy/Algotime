from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

import pandas as pd

from ..session import BreezeSession
from ..router import OrderRouter
from ..config import EngineConfig
from ..models import Position


class Strategy(ABC):
    def __init__(
        self,
        session: BreezeSession,
        router:  OrderRouter,
        cfg:     EngineConfig,
    ) -> None:
        self.session = session
        self.router  = router
        self.cfg     = cfg

    @abstractmethod
    def enter(
        self,
        chain:  pd.DataFrame,
        spot:   float,
        expiry: date,
        atm:    int,
    ) -> Optional[Position]:
        ...
