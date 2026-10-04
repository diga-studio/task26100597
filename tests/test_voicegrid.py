"""VoiceGrid 排程库自动化测试。"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from voicegrid import (
    Candidate,
    EmployeeRule,
    QuietWindow,
    SentRecord,
    build_plan,
)

UTC = timezone.utc


def ts(iso: str) -> int:
    """ISO UTC 时间串 -> UTC 秒。"""
    return int(datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp())


def no_quiet_rule(employee_id: str, tz: str = "UTC") -> EmployeeRule:
    return EmployeeRule(employee_id, tz, QuietWindow("00:00", "00:00"))


class QuotaReleaseTests(unittest.TestCase):
    """额度恰在失效时刻释放时，该通知不能发送；仍有效候选按优先级获得额度。"""

    def test_release_exactly_at_expiry(self):
        start = ts("2026-01-10T00:00:00")
        # 三条历史占满额度，最早一条在 start-10，额度在 start-10+86400 释放
        history = [
            SentRecord("emp", start - 10),
            SentRecord("emp", start - 5),
            SentRecord("emp", start - 1),
        ]
        release = start - 10 + 86400
        candidates = [
            # A 恰在额度释放时刻失效，不能发送
            Candidate("a", "emp", start, release),
            # B、C 仍有效；B 失效更早，应优先获得释放出的额度
            Candidate("b", "emp", start, release + 100),
            Candidate("c", "emp", start, release + 200),
        ]
        plan = build_plan(candidates, [no_quiet_rule("emp")], history, start)

        sends = {s.notification_id: s.send_utc for s in plan.sends}
        expired_ids = [e.notification_id for e in plan.expired]
        self.assertEqual(expired_ids, ["a"])
        # B 在额度释放瞬间发送；同秒额度（含历史）不超过 3，C 等下一次释放
        self.assertEqual(sends["b"], release)
        self.assertEqual(sends["c"], start - 5 + 86400)

    def test_same_second_sends_never_exceed_quota(self):
        start = ts("2026-01-10T00:00:00")
        history = [SentRecord("emp", start - 1)]
        candidates = [
            Candidate(f"n{i}", "emp", start, start + 200000) for i in range(4)
        ]
        plan = build_plan(candidates, [no_quiet_rule("emp")], history, start)

        sends = sorted(plan.sends, key=lambda s: (s.send_utc, s.notification_id))
        # 历史占 1 条，同秒最多再发 2 条
        self.assertEqual([s.notification_id for s in sends[:2]], ["n0", "n1"])
        self.assertEqual(sends[0].send_utc, start)
        self.assertEqual(sends[1].send_utc, start)
        # 第 3 条等最早历史释放
        self.assertEqual(sends[2].send_utc, start - 1 + 86400)
        # 第 4 条等下一条释放
        self.assertEqual(sends[3].send_utc, start + 86400)
        # 任意时刻 (t-86400, t] 内总数（含历史）不超过 3
        all_times = sorted([start - 1] + [s.send_utc for s in sends])
        from bisect import bisect_right
        for t in all_times:
            lo = bisect_right(all_times, t - 86400)
            hi = bisect_right(all_times, t)
            self.assertLessEqual(hi - lo, 3)


class DstQuietTests(unittest.TestCase):
    """America/New_York 静默 01:30-02:30，无历史，起点等于最早时刻。"""

    def rule(self) -> EmployeeRule:
        return EmployeeRule(
            "emp", "America/New_York", QuietWindow("01:30", "02:30")
        )

    def test_spring_forward_skipped_local_time(self):
        # 2026-03-08 02:00 当地跳到 03:00，02:30 不存在，静默在 07:00Z 结束
        ready = ts("2026-03-08T06:40:00")
        candidate = Candidate("n1", "emp", ready, ts("2026-03-08T08:00:00"))
        plan = build_plan([candidate], [self.rule()], [], ready)
        self.assertEqual(len(plan.sends), 1)
        self.assertEqual(plan.sends[0].send_utc, ts("2026-03-08T07:00:00"))
        self.assertEqual(plan.expired, ())

    def test_fall_back_repeated_local_time(self):
        # 2026-11-01 02:00 当地回拨到 01:00，01:00<01:30 退出静默，06:00Z 可发
        ready = ts("2026-11-01T05:40:00")
        candidate = Candidate("n1", "emp", ready, ts("2026-11-01T08:00:00"))
        plan = build_plan([candidate], [self.rule()], [], ready)
        self.assertEqual(len(plan.sends), 1)
        self.assertEqual(plan.sends[0].send_utc, ts("2026-11-01T06:00:00"))
        self.assertEqual(plan.expired, ())


class GeneralTests(unittest.TestCase):
    def test_expired_backlog_not_sent(self):
        start = ts("2026-01-10T00:00:00")
        candidates = [
            Candidate("dead", "emp", start - 1000, start - 1),   # 已失效
            Candidate("alive", "emp", start - 1000, start + 10), # 积压仍有效
        ]
        plan = build_plan(candidates, [no_quiet_rule("emp")], [], start)
        self.assertEqual([s.notification_id for s in plan.sends], ["alive"])
        self.assertEqual(plan.sends[0].send_utc, start)
        self.assertEqual([e.notification_id for e in plan.expired], ["dead"])

    def test_send_must_be_strictly_before_expiry(self):
        start = ts("2026-01-10T00:00:00")
        # 静默覆盖整个可行窗口，候选在静默结束前一刻失效
        rule = EmployeeRule("emp", "UTC", QuietWindow("00:00", "01:00"))
        candidate = Candidate("n1", "emp", start, start + 3600)
        plan = build_plan([candidate], [rule], [], start)
        self.assertEqual(plan.sends, ())
        self.assertEqual([e.notification_id for e in plan.expired], ["n1"])

    def test_overnight_quiet_window(self):
        # 跨午夜静默 22:00-06:00，UTC 时区
        rule = EmployeeRule("emp", "UTC", QuietWindow("22:00", "06:00"))
        start = ts("2026-01-10T21:00:00")
        candidates = [
            Candidate("before", "emp", start, start + 40000),
            Candidate("during", "emp", start + 3700, start + 40000),  # 22:01:40 就绪
        ]
        plan = build_plan(candidates, [rule], [], start)
        sends = {s.notification_id: s.send_utc for s in plan.sends}
        self.assertEqual(sends["before"], start)
        self.assertEqual(sends["during"], ts("2026-01-11T06:00:00"))

    def test_employees_are_independent(self):
        start = ts("2026-01-10T00:00:00")
        rules = [
            EmployeeRule("e1", "UTC", QuietWindow("00:00", "12:00")),
            no_quiet_rule("e2"),
        ]
        candidates = [
            Candidate("a", "e1", start, start + 90000),
            Candidate("b", "e2", start, start + 100),
        ]
        plan = build_plan(candidates, rules, [], start)
        sends = {s.notification_id: s.send_utc for s in plan.sends}
        self.assertEqual(sends["a"], start + 43200)  # e1 静默到中午
        self.assertEqual(sends["b"], start)          # e2 不受影响

    def test_deterministic(self):
        start = ts("2026-01-10T00:00:00")
        candidates = [
            Candidate(f"n{i}", "emp", start, start + 1000) for i in range(5)
        ]
        args = (candidates, [no_quiet_rule("emp")], [], start)
        self.assertEqual(build_plan(*args), build_plan(*args))

    def test_priority_order_expiry_then_earliest_then_id(self):
        start = ts("2026-01-10T00:00:00")
        # 历史占 2 条，同秒只剩 1 个额度，应给失效最早的候选
        history = [SentRecord("emp", start - 2), SentRecord("emp", start - 1)]
        candidates = [
            Candidate("zz", "emp", start, start + 200000),
            Candidate("aa", "emp", start, start + 200000),
            Candidate("mm", "emp", start, start + 10),
        ]
        plan = build_plan(candidates, [no_quiet_rule("emp")], history, start)
        sends = {s.notification_id: s.send_utc for s in plan.sends}
        # 失效最早的 mm 先拿额度；aa 与 zz 失效相同，按 id 字典序 aa 先
        self.assertEqual(sends["mm"], start)
        self.assertEqual(sends["aa"], start - 2 + 86400)
        self.assertEqual(sends["zz"], start - 1 + 86400)


if __name__ == "__main__":
    unittest.main()
