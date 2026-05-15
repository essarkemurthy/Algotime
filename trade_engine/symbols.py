from datetime import date, datetime, time as time_t, timedelta
from typing import Literal, Optional

# NSE weekly option month codes: Jan-Sep = 1-9, Oct = O, Nov = N, Dec = D
_WEEK_MONTH = {
    1:"1", 2:"2", 3:"3", 4:"4", 5:"5", 6:"6",
    7:"7", 8:"8", 9:"9", 10:"O", 11:"N", 12:"D",
}
_MON3 = {
    1:"JAN", 2:"FEB", 3:"MAR", 4:"APR", 5:"MAY", 6:"JUN",
    7:"JUL", 8:"AUG", 9:"SEP", 10:"OCT", 11:"NOV", 12:"DEC",
}


class SymbolBuilder:
    @staticmethod
    def weekly(underlying: str, expiry: date, strike: int, right: Literal["CE","PE"]) -> str:
        """e.g. NIFTY2341319500CE  (YY + single-char month + DD + strike + type)"""
        yy = expiry.strftime("%y")
        m  = _WEEK_MONTH[expiry.month]
        dd = f"{expiry.day:02d}"
        return f"{underlying}{yy}{m}{dd}{strike}{right}"

    @staticmethod
    def monthly(underlying: str, expiry: date, strike: int, right: Literal["CE","PE"]) -> str:
        """e.g. NIFTY23APR19500CE"""
        yy = expiry.strftime("%y")
        m  = _MON3[expiry.month]
        return f"{underlying}{yy}{m}{strike}{right}"

    @staticmethod
    def build(
        underlying: str,
        expiry: date,
        strike: int,
        right: Literal["CE","PE"],
        expiry_type: Literal["weekly","monthly"],
    ) -> str:
        return (SymbolBuilder.weekly(underlying, expiry, strike, right)
                if expiry_type == "weekly"
                else SymbolBuilder.monthly(underlying, expiry, strike, right))

    @staticmethod
    def breeze_dt(d: date) -> str:
        """ISO datetime string Breeze expects for expiry / validity date fields."""
        return datetime(d.year, d.month, d.day, 6).isoformat(timespec="milliseconds") + "Z"


def _last_thursday(year: int, month: int) -> date:
    """Last Thursday of a given month (NSE monthly expiry rule)."""
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    last_day  = first_next - timedelta(days=1)
    days_back = (last_day.weekday() - 3) % 7   # Thursday = weekday 3
    return last_day - timedelta(days=days_back)


def nearest_weekly_expiry(today: Optional[date] = None) -> date:
    today = today or date.today()
    days  = (3 - today.weekday()) % 7
    if days == 0 and datetime.now().time() > time_t(15, 30):
        days = 7
    return today + timedelta(days=days)


def nearest_monthly_expiry(today: Optional[date] = None) -> date:
    today    = today or date.today()
    this_exp = _last_thursday(today.year, today.month)
    if this_exp > today:
        return this_exp
    m = (today.month % 12) + 1
    y = today.year + (1 if today.month == 12 else 0)
    return _last_thursday(y, m)


def weekly_expiries(n: int = 2, today: Optional[date] = None) -> list:
    """Returns n upcoming weekly option expiries (Thursdays)."""
    first = nearest_weekly_expiry(today)
    return [first + timedelta(weeks=i) for i in range(n)]


def monthly_expiries(n: int = 2, today: Optional[date] = None) -> list:
    """Returns n upcoming monthly expiries (last Thursdays of calendar months)."""
    today = today or date.today()
    result: list = []
    y, m = today.year, today.month
    while len(result) < n:
        exp = _last_thursday(y, m)
        if exp >= today:
            result.append(exp)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


def all_expiries(expiry_type: str, weekly_n: int = 8,
                 monthly_n: int = 3, today: Optional[date] = None) -> list:
    """
    All upcoming option expiries for a symbol, sorted and deduplicated.

    For weekly-expiry symbols (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY):
      Returns the next weekly_n Thursdays, plus any additional monthly
      last-Thursdays that fall beyond the weekly window (up to monthly_n months
      further out). Monthly expiries already within the weekly window are
      included via the weekly set.

    For monthly-expiry symbols:
      Returns the next monthly_n monthly last-Thursdays.
    """
    if expiry_type == "monthly":
        return monthly_expiries(max(2, monthly_n), today)

    weeklies: set = set(weekly_expiries(weekly_n, today))
    last_weekly    = max(weeklies) if weeklies else (today or date.today())
    extra_monthlies = {
        m for m in monthly_expiries(monthly_n + 3, today)
        if m > last_weekly
    }
    return sorted(weeklies | extra_monthlies)
