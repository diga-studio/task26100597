"""静默区间判定。

每个真实 UTC 时刻先转换为员工当地钟面（时:分:秒），再与每日静默区间比较：
含开始、不含结束；开始晚于结束表示跨午夜；起止相同表示不静默。
夏令时回拨中重复出现的当地时间两次都适用规则；跳过的当地时间不占时长。
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .models import QuietWindow

_MAX_QUIET_SCAN_SECONDS = 26 * 3600  # 静默区间最长不超过一天，留余量


def _parse_hhmm(hhmm: str) -> int:
    """把 "HH:MM" 解析为当天秒数。"""
    parts = hhmm.split(":")
    if len(parts) != 2:
        raise ValueError(f"非法时分格式: {hhmm!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"非法时分格式: {hhmm!r}")
    return hour * 3600 + minute * 60


def _local_seconds_of_day(utc_seconds: int, tz: ZoneInfo) -> int:
    """UTC 秒对应的当地当天钟面秒数（0..86399）。"""
    local = datetime.fromtimestamp(utc_seconds, tz)
    return local.hour * 3600 + local.minute * 60 + local.second


def is_quiet(utc_seconds: int, tz: ZoneInfo, quiet: QuietWindow) -> bool:
    """判断某个 UTC 秒是否处于静默中。"""
    start = _parse_hhmm(quiet.start_hhmm)
    end = _parse_hhmm(quiet.end_hhmm)
    if start == end:
        return False
    tod = _local_seconds_of_day(utc_seconds, tz)
    if start < end:
        return start <= tod < end
    return tod >= start or tod < end


def quiet_end(utc_seconds: int, tz: ZoneInfo, quiet: QuietWindow) -> int:
    """返回 utc_seconds 所在静默段结束后的第一个非静默 UTC 秒。

    调用前需保证 is_quiet(utc_seconds) 为 True。
    逐秒扫描：回拨造成的静默中断/恢复都能被正确处理。
    """
    t = utc_seconds + 1
    limit = utc_seconds + _MAX_QUIET_SCAN_SECONDS
    while t <= limit:
        if not is_quiet(t, tz, quiet):
            return t
        t += 1
    raise RuntimeError("静默区间扫描超过 26 小时，输入可能有误")
