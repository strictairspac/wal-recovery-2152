# 初始化结构
SQLAlchemy metadata.create_all首次建users、log_sets、crash_cases、recoveries、audits、alarms、reconciliations、outbox_messages、receiver_states。log_sets.name、crash_cases.name唯一，关联使用外键，入队冻结日志和崩溃点快照。暂无在线schema升级器。

## 警报对账相关表
- alarms：超限警报锚定日志集与 write 日志 LSN，(log_set_id, lsn) 唯一，保存阈值/实测值/说明。
- reconciliations：一次崩溃恢复后的对账任务，冻结恢复编号、迟到与丢回执模拟开关、判定计划与接收方期望终态。
- outbox_messages：发件箱，message_id 为确定性幂等键（对账+警报+消息类型哈希）。状态 held（迟到模拟暂存）/pending/failed/acked，attempts 与 not_before 支撑退避重试。
- receiver_states：接收方去重账本，message_id 唯一保证重复投递幂等，alarm_id 唯一支撑警报状态机 absent→active→withdrawn，arrived_seq 记录实际到达顺序用于核对乱序。
所有状态落 PostgreSQL，worker 重启后重新捞取 reconciling 对账的到期消息继续投递；held 消息只能由演练页面显式放行。
