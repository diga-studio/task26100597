"""滚动额度：过去 86400 秒内发送总数不得超过 3（区间不含左端点、含当前秒）。"""
from __future__ import annotations

from bisect import bisect_right

WINDOW_SECONDS = 86400
MAX_SENDS = 3


def _count_in_window(sent_epochs: list[int], now_epoch: int) -> int:
    """统计 (now_epoch - 86400, now_epoch] 区间内的发送数。sent_epochs 已排序。"""
    right = bisect_right(sent_epochs, now_epoch)
    left = bisect_right(sent_epochs, now_epoch - WINDOW_SECONDS)
    return right - left


def quota_available(sent_epochs: list[int], now_epoch: int) -> bool:
    """判断 now_epoch 时刻是否还有剩余额度。sent_epochs 为已排序的已发送秒。"""
    return _count_in_window(sent_epochs, now_epoch) < MAX_SENDS


def next_release_instant(sent_epochs: list[int], now_epoch: int) -> int:
    """额度已满时，返回下一个有额度的 UTC 秒。

    窗口为 (t - 86400, t]，发送记录 s 在 t <= s + 86400 时仍占额度，
    因此额度恰在最早一条仍在窗口内的记录 + 86400 秒时释放。
    """
    left = bisect_right(sent_epochs, now_epoch - WINDOW_SECONDS)
    right = bisect_right(sent_epochs, now_epoch)
    in_window = sent_epochs[left:right]
    if len(in_window) < MAX_SENDS:
        return now_epoch
    # 需要最旧的 (len - MAX_SENDS + 1) 条滑出窗口，取其中最后一条的释放时刻
    freeing = in_window[len(in_window) - MAX_SENDS]
    return freeing + WINDOW_SECONDS
