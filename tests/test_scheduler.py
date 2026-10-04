"""VoiceGrid 排程库自动化测试。"""
from __future__ import annotations

import unittest
from datetime import datetime, time, timezone

from voicegrid import (
    EmployeeRule,
    Notification,
    SentRecord,
    build_schedule,
)

UTC = timezone.utc
NY = "America/New_York"


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


def no_quiet_rule(employee_id: str = "emp", tz: str = "UTC") -> EmployeeRule:
    return EmployeeRule(employee_id=employee_id, timezone=tz,
                        quiet_start=time(0, 0), quiet_end=time(0, 0))


class QuotaReleaseAtExpiryTest(unittest.TestCase):
    """额度恰在失效时刻释放时，该通知不能发送；仍有效候选按优先级获得额度。"""

    def test_release_exactly_at_expiry(self):
        start = at("2026-01-10T00:00:00")
        # 历史 3 条，占满额度；最早一条在 start-100，额度在 start-100+86400 释放
        release = 86400 - 100
        history = [
            SentRecord(employee_id="emp", sent_at=at("2026-01-09T23:58:20")),  # start-100
            SentRecord(employee_id="emp", sent_at=at("2026-01-09T23:59:10")),  # start-50
            SentRecord(employee_id="emp", sent_at=at("2026-01-09T23:59:50")),  # start-10
        ]
        release_at = at("2026-01-09T23:58:20").timestamp() + 86400
        self.assertEqual(int(release_at), int(start.timestamp()) + release)
        expires_exact = datetime.fromtimestamp(int(release_at), tz=UTC)
        notifications = [
            # A 恰在额度释放时刻失效：发送必须严格早于失效时刻，故不能发送
            Notification(id="a", employee_id="emp",
                         earliest=start, expires=expires_exact),
            # B 失效更晚，应在额度释放时获得发送
            Notification(id="b", employee_id="emp",
                         earliest=start,
                         expires=datetime.fromtimestamp(int(release_at) + 3600, tz=UTC)),
        ]
        result = build_schedule(notifications, [no_quiet_rule()], history, start)
        scheduled = {item.notification_id: item for item in result.scheduled}
        expired_ids = {item.notification_id for item in result.expired}
        self.assertIn("a", expired_ids)
        self.assertNotIn("a", scheduled)
        self.assertEqual(int(scheduled["b"].send_at.timestamp()), int(release_at))

    def test_same_second_sends_never_exceed_three_with_history(self):
        start = at("2026-01-10T00:00:00")
        history = [
            SentRecord(employee_id="emp", sent_at=at("2026-01-09T23:59:00")),
            SentRecord(employee_id="emp", sent_at=at("2026-01-09T23:59:30")),
        ]
        notifications = [
            Notification(id=f"n{i}", employee_id="emp",
                         earliest=start, expires=at("2026-01-12T00:00:00"))
            for i in range(5)
        ]
        result = build_schedule(notifications, [no_quiet_rule()], history, start)
        # 历史 2 条 + 同秒新发 1 条 = 3，其余需等最早历史滑出窗口
        self.assertEqual(len(result.scheduled), 5)
        first_send = int(result.scheduled[0].send_at.timestamp())
        self.assertEqual(first_send, int(start.timestamp()))
        same_second = [s for s in result.scheduled
                       if int(s.send_at.timestamp()) == first_send]
        self.assertEqual(len(same_second), 1)  # 与历史合计恰好 3
        # 任意 86400 秒窗口内（含历史）总数不超过 3
        all_sends = sorted(
            [int(r.sent_at.timestamp()) for r in history]
            + [int(s.send_at.timestamp()) for s in result.scheduled]
        )
        for i, send in enumerate(all_sends):
            window = [x for x in all_sends if send - 86400 < x <= send]
            self.assertLessEqual(len(window), 3)
        # 第二条新发送应在最早历史记录释放时发生
        second_send = int(result.scheduled[1].send_at.timestamp())
        self.assertEqual(second_send,
                         int(history[0].sent_at.timestamp()) + 86400)

    def test_same_second_multiple_sends_up_to_quota(self):
        start = at("2026-01-10T00:00:00")
        notifications = [
            Notification(id=f"n{i}", employee_id="emp",
                         earliest=start, expires=at("2026-01-10T01:00:00"))
            for i in range(3)
        ]
        result = build_schedule(notifications, [no_quiet_rule()], [], start)
        self.assertEqual(len(result.scheduled), 3)
        self.assertTrue(all(int(s.send_at.timestamp()) == int(start.timestamp())
                            for s in result.scheduled))


class DstQuietHoursTest(unittest.TestCase):
    """America/New_York 静默 01:30-02:30，无历史发送。"""

    def rule(self) -> EmployeeRule:
        return EmployeeRule(employee_id="emp", timezone=NY,
                            quiet_start=time(1, 30), quiet_end=time(2, 30))

    def test_spring_forward_2026_03_08(self):
        # 06:40:00Z = 当地 01:40 EST，静默中；02:00-02:59 当地不存在，
        # 静默实际在 07:00:00Z（当地跳到 03:00 EDT）结束
        start = at("2026-03-08T06:40:00")
        notification = Notification(id="spring", employee_id="emp",
                                    earliest=start, expires=at("2026-03-08T08:00:00"))
        result = build_schedule([notification], [self.rule()], [], start)
        self.assertEqual(len(result.scheduled), 1)
        self.assertEqual(result.scheduled[0].send_at, at("2026-03-08T07:00:00"))
        self.assertEqual(result.expired, ())

    def test_fall_back_2026_11_01(self):
        # 05:40:00Z = 当地 01:40 EDT（第一次），静默中；
        # 06:00:00Z = 当地 01:00 EST，不在静默区间，可发送
        start = at("2026-11-01T05:40:00")
        notification = Notification(id="fall", employee_id="emp",
                                    earliest=start, expires=at("2026-11-01T08:00:00"))
        result = build_schedule([notification], [self.rule()], [], start)
        self.assertEqual(len(result.scheduled), 1)
        self.assertEqual(result.scheduled[0].send_at, at("2026-11-01T06:00:00"))
        self.assertEqual(result.expired, ())


class GeneralBehaviorTest(unittest.TestCase):
    def test_expired_before_start_not_sent(self):
        start = at("2026-01-10T00:00:00")
        notifications = [
            Notification(id="dead", employee_id="emp",
                         earliest=at("2026-01-09T00:00:00"),
                         expires=at("2026-01-09T12:00:00")),
            Notification(id="alive", employee_id="emp",
                         earliest=at("2026-01-09T00:00:00"),
                         expires=at("2026-01-11T00:00:00")),
        ]
        result = build_schedule(notifications, [no_quiet_rule()], [], start)
        self.assertEqual([i.notification_id for i in result.expired], ["dead"])
        self.assertEqual([i.notification_id for i in result.scheduled], ["alive"])

    def test_priority_order_expiry_then_earliest_then_id(self):
        start = at("2026-01-10T00:00:00")
        notifications = [
            Notification(id="z", employee_id="emp",
                         earliest=start, expires=at("2026-01-10T02:00:00")),
            Notification(id="a", employee_id="emp",
                         earliest=start, expires=at("2026-01-10T01:00:00")),
            Notification(id="b", employee_id="emp",
                         earliest=start, expires=at("2026-01-10T01:00:00")),
        ]
        result = build_schedule(notifications, [no_quiet_rule()], [], start)
        self.assertEqual([s.notification_id for s in result.scheduled],
                         ["a", "b", "z"])

    def test_employees_are_independent(self):
        start = at("2026-01-10T00:00:00")
        rules = [no_quiet_rule("e1"), no_quiet_rule("e2")]
        notifications = [
            Notification(id=f"e1-n{i}", employee_id="e1",
                         earliest=start, expires=at("2026-01-11T00:00:00"))
            for i in range(3)
        ] + [
            Notification(id=f"e2-n{i}", employee_id="e2",
                         earliest=start, expires=at("2026-01-11T00:00:00"))
            for i in range(3)
        ]
        result = build_schedule(notifications, rules, [], start)
        self.assertEqual(len(result.scheduled), 6)
        self.assertTrue(all(int(s.send_at.timestamp()) == int(start.timestamp())
                            for s in result.scheduled))

    def test_deterministic_and_history_not_mutated(self):
        start = at("2026-01-10T00:00:00")
        history = [SentRecord(employee_id="emp", sent_at=at("2026-01-09T20:00:00"))]
        notifications = [
            Notification(id="n", employee_id="emp",
                         earliest=start, expires=at("2026-01-11T00:00:00")),
        ]
        first = build_schedule(notifications, [no_quiet_rule()], history, start)
        second = build_schedule(notifications, [no_quiet_rule()], history, start)
        self.assertEqual(first, second)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].sent_at, at("2026-01-09T20:00:00"))

    def test_overnight_quiet_window(self):
        start = at("2026-01-10T03:00:00")  # UTC 03:00 = 当地 03:00（UTC 时区）
        rule = EmployeeRule(employee_id="emp", timezone="UTC",
                            quiet_start=time(23, 0), quiet_end=time(6, 0))
        notification = Notification(id="n", employee_id="emp",
                                    earliest=start, expires=at("2026-01-11T00:00:00"))
        result = build_schedule([notification], [rule], [], start)
        self.assertEqual(result.scheduled[0].send_at, at("2026-01-10T06:00:00"))


if __name__ == "__main__":
    unittest.main()
