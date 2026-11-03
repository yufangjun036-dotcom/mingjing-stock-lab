"""首次任务行为测试：构造快照只验证交互与规则，不冒充真实金融数据。"""
from pathlib import Path
from unittest.mock import patch, MagicMock
from decimal import Decimal
from streamlit.testing.v1 import AppTest
from core.schemas import DatasetSnapshot, StockRecord, MetricValue
from core.beginner_task import growth_strategy, beginner_rows, plain_growth
from core.screening_engine import screen
from services.screening_service import run_screening
from services.usage_guard import UsageLimitError


def sample():
    """分别覆盖两项增长、利润减少和利润缺失。"""
    def val(n):
        return MetricValue(value=Decimal(n),quality='valid') if n else MetricValue(quality='missing',reason='构造缺失')
    return DatasetSnapshot(id='constructed-task',created_at='2026-11-04T05:40:00+08:00',available_metrics=('revenue_yoy','profit_yoy'),records=tuple(
        StockRecord(thscode=str(i),name=f'构造公司{i}',metrics=(('revenue_yoy',val(rev)),('profit_yoy',val(profit))))
        for i,(rev,profit) in enumerate([('5','3'),('5','-2'),('5',None)])))


def test_plain_results_do_not_hide_unknown_or_zero():
    """未知不写成下降；持平不写成增长；保留正确三态判断。"""
    s=sample();r=screen(s,growth_strategy());rows=beginner_rows(s,r)
    assert [x['本次判断'] for x in rows]==['符合本次条件','不符合本次条件','数据不足，暂不能确定']
    assert '减少' in rows[1]['利润变化']
    assert '构造缺失' in rows[2]['利润变化']
    assert plain_growth(MetricValue(value=Decimal('0'),quality='valid'))=='与去年同期持平'


def test_first_task_and_compare_reuse_snapshot_and_preserve_failure():
    """没有输入或阈值也能完成任务；比较不联网，失败不覆盖旧结果。"""
    snapshot=sample()
    def execute(client,strategy,snapshot_arg=None):
        return run_screening(None,strategy,snapshot_arg or snapshot)
    with patch('ui.beginner_task_panel.FuyaoClient',return_value=MagicMock()) as client, patch('ui.beginner_task_panel.run_screening',side_effect=execute):
        app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=20).run()
        assert client.call_count==0
        # 新手内容默认收起，常规输入直接可用；展开本身不会发出数据请求。
        guide = next(e for e in app.expander if e.label == '第一次使用？跟着做一次（可选）')
        assert guide.proto.expanded is False
        assert any(t.label == '描述你的选股条件' for t in app.text_area)
        assert not any(e.label == '自定义研究 · 用自己的话描述或修改专业条件' for e in app.expander)
        app.button(key='task_fetch').click().run()
        assert not app.exception
        assert client.call_count==1
        assert app.session_state['task_result'].rows[0].status=='selected'
        assert app.session_state['task_result'].rows[1].status=='excluded'
        app.button(key='task_compare').click().run()
        assert not app.exception
        assert client.call_count==1
        assert app.session_state['task_snapshot'].id=='constructed-task'
        assert all(r.status=='selected' for r in app.session_state['task_result'].rows)
        assert len(app.session_state['task_changes'])==2
        with patch('ui.beginner_task_panel.run_screening',side_effect=UsageLimitError('本会话每分钟最多两个外部操作')):
            app.button(key='task_fetch').click().run()
        assert not app.exception
        assert '每分钟最多两个' in app.session_state['task_error']
        assert app.session_state['task_snapshot'].id=='constructed-task'
