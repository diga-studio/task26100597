"""VoiceGrid 员工通知排程库：数据类型定义。

所有时间均为带时区的 datetime（库内统一换算为 UTC 秒处理）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time


@dataclass(frozen=True)
class Notification:
    """一条候选通知。"""

    id: str
    employee_id: str
    earliest: datetime  # 最早发送时刻（含）
    expires: datetime  # 失效时刻（不含，发送必须严格早于此刻）


@dataclass(frozen=True)
class EmployeeRule:
    """员工规则：IANA 时区 + 每日静默区间（当地时分，含开始、不含结束）。

    quiet_start 晚于 quiet_end 表示跨午夜；两者相等表示不静默。
    """

    employee_id: str
    timezone: str
    quiet_start: time
    quiet_end: time


@dataclass(frozen=True)
class SentRecord:
    """一条历史发送记录（视为合法且不晚于排程起点）。"""

    employee_id: str
    sent_at: datetime


@dataclass(frozen=True)
class ScheduledItem:
    """已安排发送的通知。"""

    notification_id: str
    employee_id: str
    send_at: datetime


@dataclass(frozen=True)
class ExpiredItem:
    """来不及发送、到期未发送的通知。"""

    notification_id: str
    employee_id: str


@dataclass(frozen=True)
class ScheduleResult:
    """排程结果：已安排 + 到期未发送。"""

    scheduled: tuple[ScheduledItem, ...]
    expired: tuple[ExpiredItem, ...]
