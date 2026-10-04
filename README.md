# VoiceGrid 员工通知排程库

接收通知候选、员工规则与已发送历史，生成遵守每日静默规则和滚动发送额度
（任意 86400 秒窗口内每人最多 3 条）的发送计划，并标明来不及发送的通知。
库内数据只存内存，不负责实际投递；相同输入必得相同结果。

## 运行测试

```bash
python3 -m unittest discover -s tests -v
```

## 调用方式

所有时刻均为 UTC Unix 秒（`int`）。发送时刻 `t` 满足
`earliest_utc <= t < expiry_utc` 且 `t >= start_utc`。

```python
from voicegrid import (
    Candidate, EmployeeRule, QuietWindow, SentRecord, build_plan,
)

plan = build_plan(
    candidates=[
        Candidate("n1", "emp-1", earliest_utc=1772952000, expiry_utc=1772956800),
    ],
    rules=[
        EmployeeRule("emp-1", "America/New_York", QuietWindow("01:30", "02:30")),
    ],
    history=[SentRecord("emp-1", sent_utc=1772950000)],
    start_utc=1772952000,
)

for send in plan.sends:      # ScheduledSend(notification_id, employee_id, send_utc)
    print("发送", send.notification_id, "于", send.send_utc)
for exp in plan.expired:     # ExpiredNotification(notification_id, employee_id)
    print("到期未发送", exp.notification_id)
```

## 规则摘要

- 静默区间用当地 `"HH:MM"` 表示，含开始、不含结束；开始晚于结束为跨午夜；
  起止相同表示不静默。按转换后的当地钟面判断，夏令时回拨重复的当地时间
  两次都适用，跳过的当地时间不占时长。
- 滚动额度按真实经过的 86400 秒计算（`(t-86400, t]`，不含左端点），
  历史发送计入；同一秒可发多条，每条都占额度。
- 贪心调度：有就绪候选、不静默且有额度时立即发送，不为未来通知预留额度；
  就绪候选按 (失效时刻, 最早时刻, 通知标识) 字典序排序，每发一条重新检查额度。
- 员工之间互不影响；计划仅预测，不改写已发送历史。
