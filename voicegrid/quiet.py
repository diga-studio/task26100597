"""每日静默区间判断（按员工当地钟面，正确处理夏令时）。

规则：起止使用当地时分，包含开始、不包含结束；开始晚于结束表示跨午夜；
起止相同表示不静默。每个真实 UTC 时刻都按转换后的当地钟面判断：
夏令时回拨中重复出现的当地时间两次都适用规则，跳过的当地时间不占时长。
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_UTC = timezone.utc


def _local_tod(utc_epoch: int, tz: ZoneInfo) -> time:
    return datetime.fromtimestamp(utc_epoch, tz=_UTC).astimezone(tz).time()


def is_quiet(utc_epoch: int, tz_name: str, quiet_start: time, quiet_end: time) -> bool:
    """判断某个 UTC 秒是否处于员工当地静默区间内。"""
    if quiet_start == quiet_end:
        return False
    tod = _local_tod(utc_epoch, ZoneInfo(tz_name))
    if quiet_start < quiet_end:
        return quiet_start <= tod < quiet_end
    return tod >= quiet_start or tod < quiet_end


def _naive_local_to_utc(naive: datetime, tz: ZoneInfo) -> list[int]:
    """把当地钟面时刻解析为真实 UTC 秒：不存在（春跳）返回空，重复（秋回拨）返回两个。"""
    out: list[int] = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=tz, fold=fold)
        utc = aware.astimezone(_UTC)
        if utc.astimezone(tz).replace(tzinfo=None) == naive:
            out.append(int(utc.timestamp()))
    return sorted(set(out))


def _dst_transitions(tz: ZoneInfo, start_epoch: int, end_epoch: int) -> list[int]:
    """找出 [start_epoch, end_epoch] 内所有 UTC 偏移发生跳变的秒。"""
    def offset(epoch: int):
        return datetime.fromtimestamp(epoch, tz=_UTC).astimezone(tz).utcoffset()

    out: list[int] = []
    step = 3600
    prev_epoch = start_epoch
    prev_offset = offset(prev_epoch)
    epoch = start_epoch + step
    while epoch <= end_epoch + step:
        current = offset(epoch)
        if current != prev_offset:
            lo, hi = prev_epoch, epoch
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if offset(mid) == prev_offset:
                    lo = mid
                else:
                    hi = mid
            out.append(hi)
            prev_offset = current
        prev_epoch = epoch
        epoch += step
    return out


def quiet_end_instant(utc_epoch: int, tz_name: str, quiet_start: time, quiet_end: time) -> int:
    """给定一个处于静默中的 UTC 秒，返回静默结束的 UTC 秒（该秒起不再静默）。

    静默状态只可能在两类边界改变：当地钟面走到 quiet_end，或夏令时跳变
    （春跳会跳过部分当地时间）。枚举两类候选边界，取第一个不再静默的时刻。
    """
    tz = ZoneInfo(tz_name)
    local_date = datetime.fromtimestamp(utc_epoch, tz=_UTC).astimezone(tz).date()
    candidates: set[int] = set()
    for delta in (-1, 0, 1, 2):
        naive = datetime.combine(local_date + timedelta(days=delta), quiet_end)
        candidates.update(_naive_local_to_utc(naive, tz))
    candidates.update(_dst_transitions(tz, utc_epoch, utc_epoch + 3 * 86400))
    for boundary in sorted(candidates):
        if boundary > utc_epoch and not is_quiet(boundary, tz_name, quiet_start, quiet_end):
            return boundary
    raise RuntimeError("quiet end not found within search horizon")
