ROLES = ('admin', 'operator', 'viewer')
DRILL_STATUSES = ('queued', 'running', 'completed', 'failed')

# 对账任务状态：补偿已入队但接收方尚未全部确认 / 全部回执已到且状态一致
RECONCILE_STATUSES = ('reconciling', 'confirmed')
# 发件箱消息状态：延迟投递 / 待投递 / 已确认 / 投递失败等待重试
OUTBOX_STATUSES = ('held', 'pending', 'acked', 'failed')
# 消息类型：原始超限警报 / 撤警补偿
MESSAGE_TYPES = ('alarm', 'compensation')
# 接收方侧每个警报的生命周期：未到达 / 生效中 / 已撤警
RECEIVER_STATES = ('absent', 'active', 'withdrawn')
