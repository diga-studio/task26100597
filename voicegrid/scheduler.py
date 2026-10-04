"""排程器：按静默规则与滚动额度生成发送计划。

规则要点：
- 发送时刻 t 满足 earliest_utc <= t < expiry_utc，且 t >= 排程起点。
- 每次安排后，该员工 (t-86400, t] 内发送总数（含历史）不得超过 3。
- 贪心：只要有就绪候选、当前不静默、有剩余额度，就立即发送；
  就绪候选按 (失效时刻, 最早时刻, 通知标识) 字典序取优先级。
- 员工之间互不影响；计划仅预测，不改写历史；相同输入结果相同。
"""

from __future__ import annotations

import heapq
from bisect import bisect_left, bisect_right, insort
from zoneinfo import ZoneInfo

from .models import (
    Candidate,
    EmployeeRule,
    ExpiredNotification,
    Plan,
    QuietWindow,
    ScheduledSend,
    SentRecord,
)
from .quiet import is_quiet, quiet_end

QUOTA_LIMIT = 3
QUOTA_WINDOW_SECONDS = 86400


def _schedule_employee(
    employee_id: str,
    candidates: list[Candidate],
    tz: ZoneInfo,
    quiet: QuietWindow,
    history: list[int],
    start_utc: int,
) -> tuple[list[ScheduledSend], list[ExpiredNotification]]:
    """为单个员工生成发送计划与到期未发送列表。"""
    sends: list[ScheduledSend] = []
    expired: list[ExpiredNotification] = []

    sent_times = sorted(history)  # 已发送时刻（历史 + 新安排），升序

    def quota_ok(t: int) -> bool:
        lo = bisect_right(sent_times, t - QUOTA_WINDOW_SECONDS)
        hi = bisect_right(sent_times, t)
        return hi - lo < QUOTA_LIMIT

    def quota_release(t: int) -> int:
        """额度满时，下一额度释放的最早时刻。"""
        lo = bisect_right(sent_times, t - QUOTA_WINDOW_SECONDS)
        hi = bisect_right(sent_times, t)
        blocking = sent_times[lo:hi]
        if len(blocking) < QUOTA_LIMIT:
            return t
        return blocking[0] + QUOTA_WINDOW_SECONDS

    # 未到最早时刻的候选，按 (最早时刻, 失效时刻, 标识) 排序
    pending: list[tuple[int, int, str, Candidate]] = []
    # 已就绪候选堆，按 (失效时刻, 最早时刻, 标识) 排序
    ready: list[tuple[int, int, str, Candidate]] = []
    for c in candidates:
        heapq.heappush(pending, (c.earliest_utc, c.expiry_utc, c.notification_id, c))
    heapq.heapify(ready)

    t = start_utc
    while pending or ready:
        # 把已到最早时刻的候选移入就绪堆
        while pending and pending[0][0] <= t:
            _, _, _, c = heapq.heappop(pending)
            heapq.heappush(ready, (c.expiry_utc, c.earliest_utc, c.notification_id, c))
        # 清理已失效（无法发送）的候选
        while ready and ready[0][0] <= t:
            _, _, _, c = heapq.heappop(ready)
            expired.append(ExpiredNotification(c.notification_id, c.employee_id))
        if not ready and not pending:
            break

        if ready and not is_quiet(t, tz, quiet) and quota_ok(t):
            _, _, _, c = heapq.heappop(ready)
            sends.append(ScheduledSend(c.notification_id, c.employee_id, t))
            insort(sent_times, t)
            continue  # 同一秒可继续发送，重新检查额度

        # 当前无法发送，推进到下一个可能改变状态的时刻
        next_t: int | None = None
        if ready:
            # 有就绪候选但被静默或额度阻塞
            if is_quiet(t, tz, quiet):
                next_t = quiet_end(t, tz, quiet)
            if not quota_ok(t):
                release = quota_release(t)
                next_t = release if next_t is None else min(next_t, release)
            # 阻塞期间最早失效时刻也要检查，避免跳过失效处理
            soonest_expiry = ready[0][0]
            if next_t is None or soonest_expiry < next_t:
                next_t = soonest_expiry
        else:
            # 无就绪候选，等下一条到最早时刻
            next_t = pending[0][0]
        if pending and pending[0][0] > t and (next_t is None or pending[0][0] < next_t):
            next_t = pending[0][0]
        if next_t is None or next_t <= t:
            next_t = t + 1
        t = next_t

    return sends, expired


def build_plan(
    candidates: list[Candidate],
    rules: list[EmployeeRule],
    history: list[SentRecord],
    start_utc: int,
) -> Plan:
    """生成发送计划。

    candidates: 候选通知（含仍有效的积压通知）。
    rules: 每名员工的时区与静默规则。
    history: 已发送历史，视为合法且不晚于 start_utc。
    start_utc: 排程起点，UTC 秒。
    """
    rule_by_employee = {r.employee_id: r for r in rules}
    history_by_employee: dict[str, list[int]] = {}
    for record in history:
        history_by_employee.setdefault(record.employee_id, []).append(record.sent_utc)
    candidates_by_employee: dict[str, list[Candidate]] = {}
    for c in candidates:
        candidates_by_employee.setdefault(c.employee_id, []).append(c)

    all_sends: list[ScheduledSend] = []
    all_expired: list[ExpiredNotification] = []
    for employee_id in sorted(candidates_by_employee):
        rule = rule_by_employee.get(employee_id)
        if rule is None:
            raise ValueError(f"缺少员工规则: {employee_id!r}")
        sends, expired = _schedule_employee(
            employee_id,
            candidates_by_employee[employee_id],
            ZoneInfo(rule.iana_timezone),
            rule.quiet,
            history_by_employee.get(employee_id, []),
            start_utc,
        )
        all_sends.extend(sends)
        all_expired.extend(expired)

    all_sends.sort(key=lambda s: (s.send_utc, s.notification_id))
    all_expired.sort(key=lambda e: e.notification_id)
    return Plan(sends=tuple(all_sends), expired=tuple(all_expired))
