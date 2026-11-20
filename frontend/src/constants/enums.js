export const ROLES = {admin:'管理员',operator:'操作员',viewer:'观察员'};
export const DRILL_STATUSES = {queued:'等待执行',running:'执行中',completed:'已完成',failed:'失败'};
export const RECONCILE_STATUSES = {reconciling:'对账中',confirmed:'已确认'};
export const OUTBOX_STATUSES = {held:'迟到暂存',pending:'待投递',acked:'已回执',failed:'丢回执重试'};
export const MESSAGE_TYPES = {alarm:'原始警报',compensation:'撤警补偿'};
export const RECEIVER_STATES = {absent:'未到达',active:'生效中',withdrawn:'已撤警'};
export const ALARM_VERDICTS = {valid:'有效保留',false_alarm:'误报撤警',not_durable:'未落盘不发警'};
