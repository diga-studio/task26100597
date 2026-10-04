# VoiceGrid 员工通知排程库

接收通知候选并生成遵守静默规则和滚动额度的发送计划，明确哪些通知来不及发送。
候选、员工规则和已发送历史由调用方提供，库内数据只存内存，不负责实际投递。

## 规则摘要

- 发送不得早于候选的最早发送时刻，且必须严格早于失效时刻；已失效候选不发送。
- 每名员工有 IANA 时区和每日静默区间（当地时分，含开始、不含结束；开始晚于
  结束表示跨午夜；起止相同表示不静默）。夏令时回拨中重复的当地时间两次都适用，
  跳过的当地时间不占时长。
- 每次安排发送后，该员工过去 86400 秒（真实经过时间，区间不含左端点、含当前秒）
  内的发送总数不超过 3；调用方提供的历史发送计入额度；同一秒可发送多条。
- 只要有可发送候选就立即安排，不为尚未到时的通知预留额度；候选按
  （失效时刻、最早发送时刻、通知标识字典序）排序，每安排一条重新考虑额度。
- 员工之间互不影响；计划仅预测，不改写历史；相同输入必得相同结果。

## 调用方式

```python
from datetime import datetime, time, timezone
from voicegrid import EmployeeRule, Notification, SentRecord, build_schedule

notifications = [
    Notification(
        id="msg-1",
        employee_id="alice",
        earliest=datetime(2026, 3, 8, 6, 40, tzinfo=timezone.utc),
        expires=datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc),
    ),
]
rules = [
    EmployeeRule(
        employee_id="alice",
        timezone="America/New_York",
        quiet_start=time(1, 30),
        quiet_end=time(2, 30),
    ),
]
history = [
    SentRecord(employee_id="alice",
               sent_at=datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)),
]

result = build_schedule(notifications, rules, history,
                        start=datetime(2026, 3, 8, 6, 40, tzinfo=timezone.utc))

for item in result.scheduled:   # ScheduledItem(notification_id, employee_id, send_at)
    print("发送", item.notification_id, "于", item.send_at)
for item in result.expired:     # ExpiredItem(notification_id, employee_id)
    print("到期未发送", item.notification_id)
```

- 所有 `datetime` 必须带时区；库内统一按 UTC 秒处理。
- `build_schedule` 不修改传入的任何对象，返回 `ScheduleResult(scheduled, expired)`。

## 运行测试

```bash
python3 -m unittest discover -s tests -v
```

仅依赖 Python 标准库（3.9+，需 `zoneinfo` 时区数据）。
