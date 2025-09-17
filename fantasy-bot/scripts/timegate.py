import pytz
from datetime import datetime, timedelta
from .utils import get_env

def should_run(kind: str, tz_name: str) -> bool:
    """
    kind: 'preview' or 'recap'
    Uses env PREVIEW_DAY/PREVIEW_HOUR or RECAP_DAY/RECAP_HOUR.
    Allows a +/- 30 minute window so a top-of-hour cron works.
    """
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)

    if kind == "preview":
        day = get_env("PREVIEW_DAY", "Thursday")
        hour = int(get_env("PREVIEW_HOUR", 9))
    else:
        day = get_env("RECAP_DAY", "Wednesday")
        hour = int(get_env("RECAP_HOUR", 9))

    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    # Align target to requested weekday this week
    weekday_map = {
        "Monday":0,"Tuesday":1,"Wednesday":2,"Thursday":3,"Friday":4,"Saturday":5,"Sunday":6
    }
    desired_wd = weekday_map[day]
    delta_days = (desired_wd - now.weekday()) % 7
    target = (now + timedelta(days=delta_days)).replace(hour=hour, minute=0, second=0, microsecond=0)

    window_start = target - timedelta(minutes=30)
    window_end   = target + timedelta(minutes=30)

    return window_start <= now <= window_end
