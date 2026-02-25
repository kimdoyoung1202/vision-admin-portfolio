from django.utils import timezone
from datetime import timedelta

def get_range(range_key: str):
    now = timezone.localtime()

    if range_key == "month":
        # 이번달 1일 0시 ~ 현재
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now
        return start, end

    if range_key == "week":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        end = now
        return start, end

    # day
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now
    return start, end


def get_prev_range(range_key: str):
    """
    KPI 증감(전일/전주)을 위해 '직전 기간'을 구함.
    - day : 어제 0시 ~ 어제 0시+오늘 경과시간
    - week: 지난주 월요일 0시 ~ 지난주 월요일+이번주 경과시간
    """
    now = timezone.localtime()

    if range_key == "week":
        cur_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        elapsed = now - cur_start
        prev_start = cur_start - timedelta(days=7)
        prev_end = prev_start + elapsed
        return prev_start, prev_end

    cur_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = now - cur_start
    prev_start = cur_start - timedelta(days=1)
    prev_end = prev_start + elapsed
    return prev_start, prev_end