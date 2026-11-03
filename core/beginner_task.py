"""首次使用任务的固定条件与白话结果；完全复用原筛选引擎。"""
from core.schemas import Condition, Strategy


def growth_strategy(income_only=False):
    """增长指同比严格大于0；单项比较只移除利润条件，不改数据。"""
    metrics = ['revenue_yoy'] if income_only else ['revenue_yoy', 'profit_yoy']
    return Strategy(conditions=tuple(Condition(id=f'c{i+1}', metric_id=m,
                                              operator='>', value='0') for i,m in enumerate(metrics)))


def plain_growth(value):
    """只描述有效观测；未知原因直接保留，0不写成增加或减少。"""
    if value is None or value.quality != 'valid':
        return '暂时无法判断' + (f'：{value.reason}' if value and value.reason else '')
    number = value.value
    if number == 0:
        return '与去年同期持平'
    return f"比去年同期{'增加' if number > 0 else '减少'} {abs(number):.2f}%"


def beginner_rows(snapshot, result):
    """将每家公司两个指标与当前筛选状态对应，避免从结果状态猜缺失原因。"""
    records = {r.thscode: r for r in snapshot.records}
    labels = {'selected':'符合本次条件', 'excluded':'不符合本次条件', 'unknown':'数据不足，暂不能确定'}
    rows = []
    for row in result.rows:
        metrics = dict(records[row.thscode].metrics)
        rows.append({'公司':row.name, '代码':row.thscode,
                     '收入变化':plain_growth(metrics.get('revenue_yoy')),
                     '利润变化':plain_growth(metrics.get('profit_yoy')),
                     '本次判断':labels[row.status]})
    return rows
