"""
report_periods.py — pure date-window helpers for the paper-trading period reports.

Kept separate from app.py so it can be unit-tested without importing the whole
FastAPI app (and its heavy deps). Financial year = Indian FY (Apr 1 – Mar 31).
"""
import calendar
from datetime import date
from typing import Optional, Tuple


def months_ago(d: date, n: int) -> date:
    """d shifted back n months, clamping the day to the target month's length."""
    m = d.month - 1 - n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def fy_bounds(fy_start_year: int) -> Tuple[date, date]:
    """Indian financial year: Apr 1 (fy_start_year) → Mar 31 (fy_start_year + 1)."""
    return date(fy_start_year, 4, 1), date(fy_start_year + 1, 3, 31)


def period_range(period: str, fy: Optional[int] = None,
                 frm: Optional[str] = None, to: Optional[str] = None,
                 today: Optional[date] = None) -> Tuple[Optional[date], Optional[date]]:
    """Resolve a report period → (from_date|None, to_date|None). Explicit frm/to
    override the preset. `today` is injectable for testing."""
    if frm or to:
        return (date.fromisoformat(frm) if frm else None,
                date.fromisoformat(to) if to else None)
    today = today or date.today()
    p = (period or "1m").lower()
    if p == "all":
        return None, None
    if p == "fy":
        start_year = fy if fy is not None else (today.year if today.month >= 4 else today.year - 1)
        f, t = fy_bounds(start_year)
        return f, min(t, today)
    if p == "ytd":
        return date(today.year, 1, 1), today
    months = {"1m": 1, "3m": 3, "6m": 6, "1y": 12}.get(p, 1)
    return months_ago(today, months), today
