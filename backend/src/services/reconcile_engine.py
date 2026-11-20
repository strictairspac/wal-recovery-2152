"""超限警报对账纯函数模型。

崩溃恢复后，只有已提交（winner）写入发出的警报仍然有效；未提交（loser）或已回滚
（aborted）写入发出的警报属于误报，必须向接收方补发撤警补偿。消息顺序与回执均不可靠，
幂等判定集中在本模块与接收方服务，保证乱序不复活、重试不重复撤警。
"""
from __future__ import annotations
import hashlib


def _write_index(records):
    """LSN -> write 记录索引，校验警报必须锚定一条 write 日志。"""
    index = {}
    for lsn, rec in enumerate(records, 1):
        if rec.get('op') == 'write':
            index[lsn] = rec
    return index


def validate_alarm(records, lsn, key, threshold, observed):
    if not isinstance(lsn, int) or lsn < 1 or lsn > len(records):
        raise ValueError('警报日志位置必须在 1—日志条数之间')
    rec = records[lsn - 1]
    if rec.get('op') != 'write':
        raise ValueError(f'LSN {lsn} 不是 write 日志，警报必须锚定采样写入')
    if key != rec.get('key'):
        raise ValueError(f'LSN {lsn} 写入键为 {rec.get("key")}，与警报键不一致')
    if not isinstance(threshold, int) or isinstance(threshold, bool):
        raise ValueError('阈值必须为整数')
    if not isinstance(observed, int) or isinstance(observed, bool):
        raise ValueError('实测值必须为整数')
    if observed <= threshold:
        raise ValueError('仅录入超限警报：实测值必须大于阈值')
    return True


def classify(alarm, recovery_result, write_idx):
    """按恢复结果判定单条警报是否仍然有效。

    - 警报 LSN 在崩溃前缀之外：写入从未落盘，警报不成立（not_durable）。
    - 锚定事务在 winner 列表：已提交，警报有效（valid）。
    - 锚定事务在 aborted/loser 列表或被 undo 轨迹撤销：误报，需要补偿（false_alarm）。
    """
    lsn = alarm['lsn']
    crash_after = recovery_result['crash_after']
    if lsn > crash_after:
        return 'not_durable'
    rec = write_idx.get(lsn)
    tx = rec['tx'] if rec else None
    if tx in recovery_result.get('committed', []):
        return 'valid'
    if tx in recovery_result.get('aborted', []) or tx in recovery_result.get('losers', []):
        return 'false_alarm'
    # 防御分支：崩溃前缀内的写入事务必属于 winner/aborted/loser 之一
    undone_tx = {t.get('tx') for t in recovery_result.get('trace', []) if t.get('phase') == 'undo_loser'}
    return 'false_alarm' if tx in undone_tx else 'valid'


def message_id(reconciliation_id, alarm_id, msg_type):
    """确定性幂等键：同一对账、同一警报、同一消息类型永远只有一个 ID。"""
    raw = f'rec{reconciliation_id}:alm{alarm_id}:{msg_type}'
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f'{msg_type}-r{reconciliation_id}-a{alarm_id}-{digest}'


def build_plan(alarms, recovery_result, records, reconciliation_id):
    """生成发件箱投递计划与每条警报的判定结论（纯函数，不触碰数据库）。

    - valid：已提交写入的警报，投递原始警报，接收方保持 active。
    - false_alarm：未提交/已回滚写入的警报，先投递原始警报再投递撤警补偿，终态 withdrawn。
    - not_durable：锚定写入在崩溃前缀之外、从未落盘，不产生任何消息，接收方保持 absent。
    """
    write_idx = _write_index(records)
    plan = []
    for alarm in alarms:
        verdict = classify(alarm, recovery_result, write_idx)
        if verdict == 'not_durable':
            entries = []
        else:
            entries = [{
                'alarm_id': alarm['id'], 'msg_type': 'alarm',
                'message_id': message_id(reconciliation_id, alarm['id'], 'alarm'),
                'verdict': verdict,
            }]
            if verdict == 'false_alarm':
                entries.append({
                    'alarm_id': alarm['id'], 'msg_type': 'compensation',
                    'message_id': message_id(reconciliation_id, alarm['id'], 'compensation'),
                    'verdict': verdict,
                })
        plan.append({'alarm': alarm, 'verdict': verdict, 'messages': entries})
    return plan


def expected_final_state(plan):
    """接收方最终应呈现的警报状态：有效警报 active，误报/未落盘警报 withdrawn 或 absent。"""
    expected = {}
    for item in plan:
        if item['verdict'] == 'valid':
            expected[item['alarm']['id']] = 'active'
        elif item['verdict'] == 'false_alarm':
            expected[item['alarm']['id']] = 'withdrawn'
        else:
            expected[item['alarm']['id']] = 'absent'
    return expected
