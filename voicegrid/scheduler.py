"""排程主逻辑：接收候选通知，生成遵守静默规则和滚动额度的发送计划。

贪心事件模拟：只要有已到最早发送时刻且未失效的候选，并且当前不静默、
有剩余额度，就立即安排发送，不为尚未到时的通知预留额度。每安排一条，
都重新考虑剩余额度。员工之间互不影响。计划仅预测，不改写已发送历史。
"""
from __future__ import annotations

from bisect import insort
from datetime import datetime, timezone
from typing import Iterable

from .models import (
    EmployeeRule,
    ExpiredItem,
    Notification,
    ScheduleResult,
    ScheduledItem,
    SentRecord,
)
from .quiet import is_quiet, quiet_end_instant
from .quota import next_release_instant, quota_available

_UTC = timezone.utc


def _to_epoch(moment: datetime) -> int:
    if moment.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return int(moment.timestamp())


def _to_utc(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=_UTC)


def _schedule_employee(
    notifications: list[Notification],
    rule: EmployeeRule,
    sent_epochs: list[int],
    start_epoch: int,
) -> tuple[list[ScheduledItem], list[ExpiredItem]]:
    # 可选通知依次按失效时刻、最早发送时刻、通知标识字典序排序
    keyed = sorted(
        ((_to_epoch(n.expires), _to_epoch(n.earliest), n.id, n) for n in notifications),
        key=lambda item: (item[0], item[1], item[2]),
    )
    pending = [(expires_e, earliest_e, nid, n) for expires_e, earliest_e, nid, n in keyed]
    sent = sorted(sent_epochs)
    scheduled: list[ScheduledItem] = []
    expired: list[ExpiredItem] = []
    tz_name = rule.timezone
    qs, qe = rule.quiet_start, rule.quiet_end
    t = start_epoch

    while pending:
        # 清理在当前时刻或之前已失效的候选
        still_pending = []
        for entry in pending:
            if entry[0] <= t:
                expired.append(ExpiredItem(notification_id=entry[2], employee_id=entry[3].employee_id))
            else:
                still_pending.append(entry)
        pending = still_pending
        if not pending:
            break

        ready = [entry for entry in pending if entry[1] <= t]
        if ready and not is_quiet(t, tz_name, qs, qe) and quota_available(sent, t):
            chosen = ready[0]
            scheduled.append(
                ScheduledItem(
                    notification_id=chosen[2],
                    employee_id=chosen[3].employee_id,
                    send_at=_to_utc(t),
                )
            )
            insort(sent, t)
            pending.remove(chosen)
            continue

        # 计算下一个可能改变状态的时刻
        next_instants: list[int] = []
        future = [entry[1] for entry in pending if entry[1] > t]
        if future:
            next_instants.append(min(future))
        if is_quiet(t, tz_name, qs, qe):
            next_instants.append(quiet_end_instant(t, tz_name, qs, qe))
        if not quota_available(sent, t):
            next_instants.append(next_release_instant(sent, t))
        if not next_instants:
            break
        t = min(next_instants)

    for entry in pending:
        expired.append(ExpiredItem(notification_id=entry[2], employee_id=entry[3].employee_id))
    return scheduled, expired


def build_schedule(
    notifications: Iterable[Notification],
    rules: Iterable[EmployeeRule],
    history: Iterable[SentRecord],
    start: datetime,
) -> ScheduleResult:
    """从 start 起为候选通知生成发送计划；来不及发送的标记为到期未发送。

    相同输入必然得到相同结果；本函数不修改调用方提供的任何数据。
    """
    start_epoch = _to_epoch(start)
    rule_by_employee = {r.employee_id: r for r in rules}
    history_by_employee: dict[str, list[int]] = {}
    for record in history:
        history_by_employee.setdefault(record.employee_id, []).append(_to_epoch(record.sent_at))
    notifications_by_employee: dict[str, list[Notification]] = {}
    for notification in notifications:
        notifications_by_employee.setdefault(notification.employee_id, []).append(notification)

    scheduled: list[ScheduledItem] = []
    expired: list[ExpiredItem] = []
    for employee_id in sorted(notifications_by_employee):
        rule = rule_by_employee.get(employee_id)
        if rule is None:
            raise ValueError(f"missing rule for employee {employee_id!r}")
        employee_scheduled, employee_expired = _schedule_employee(
            notifications_by_employee[employee_id],
            rule,
            history_by_employee.get(employee_id, []),
            start_epoch,
        )
        scheduled.extend(employee_scheduled)
        expired.extend(employee_expired)

    scheduled.sort(key=lambda item: (_to_epoch(item.send_at), item.employee_id, item.notification_id))
    expired.sort(key=lambda item: (item.employee_id, item.notification_id))
    return ScheduleResult(scheduled=tuple(scheduled), expired=tuple(expired))
