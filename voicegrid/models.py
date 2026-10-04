"""VoiceGrid 数据模型：候选通知、员工规则、发送历史与排程结果。

所有时刻均为 UTC Unix 秒（int）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Candidate:
    """一条候选通知。"""

    notification_id: str
    employee_id: str
    earliest_utc: int  # 最早发送时刻（含），UTC 秒
    expiry_utc: int    # 失效时刻（不含），UTC 秒


@dataclass(frozen=True)
class QuietWindow:
    """每日静默区间，当地时分，含开始、不含结束。

    start == end 表示不静默；start > end 表示跨午夜。
    """

    start_hhmm: str  # "HH:MM"
    end_hhmm: str    # "HH:MM"


@dataclass(frozen=True)
class EmployeeRule:
    """员工规则：IANA 时区 + 每日静默区间。"""

    employee_id: str
    iana_timezone: str
    quiet: QuietWindow


@dataclass(frozen=True)
class SentRecord:
    """一条已发送历史记录。"""

    employee_id: str
    sent_utc: int  # UTC 秒，不晚于排程起点


@dataclass(frozen=True)
class ScheduledSend:
    """计划中的一条发送。"""

    notification_id: str
    employee_id: str
    send_utc: int


@dataclass(frozen=True)
class ExpiredNotification:
    """来不及发送、到期未发送的通知。"""

    notification_id: str
    employee_id: str


@dataclass(frozen=True)
class Plan:
    """排程结果：发送计划 + 到期未发送列表。"""

    sends: tuple[ScheduledSend, ...] = ()
    expired: tuple[ExpiredNotification, ...] = ()
