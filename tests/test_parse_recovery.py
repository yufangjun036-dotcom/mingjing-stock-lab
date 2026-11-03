"""解析到取数的交互回归：测试替身不计作真实模型准确率。"""
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from core.intent_parser import IntentDraft,DraftCondition
from services.usage_guard import UsageGuard

APP=Path(__file__).resolve().parents[1]/'app.py'

def draft():
    """明确的两条估值条件，供交互状态测试。"""
    return IntentDraft(conditions=[DraftCondition(metric_id='pe_ttm',operator='>',value='0'),DraftCondition(metric_id='pe_ttm',operator='<=',value='25')],assumptions=[],clarifications=[],unsupported=[],refusal_reason='')

def press(app,label):
    """按用户可见标签点击并触发页面重跑。"""
    next(b for b in app.button if b.label==label).click().run()

def test_identical_parse_then_fetch_uses_only_two_operations(tmp_path):
    """真实限额器下首次解析、同文重复解析和取数应走完而非占三次额度。"""
    guard=UsageGuard(tmp_path/'usage.db')
    envelope={'endpoint':'/constructed','request_id':'test','retrieved_at':'2026-11-04T00:00:00+08:00','data':{'timestamp':1793721600000,'item':[{'thscode':'600519.SH','name':'构造股票','pe_ttm':10,'pb_mrq':2}]}}
    with patch('services.usage_guard.get_usage_guard',return_value=guard),patch('ui.external_operation.get_usage_guard',return_value=guard),patch('core.intent_parser.parse_intent',return_value=draft()) as parse,patch('data.provider.FuyaoClient.get_valuations',return_value=envelope),patch('ui.external_operation.run_external_operation', wraps=__import__('ui.external_operation',fromlist=['run_external_operation']).run_external_operation):
        app=AppTest.from_file(APP,default_timeout=20).run()
        app.text_area[0].set_value('市盈率大于0且不超过25倍')
        press(app,'让 AI 解析')
        press(app,'让 AI 解析')
        assert parse.call_count==1
        app.checkbox[0].check().run()
        assert not next(b for b in app.button if b.label=='获取真实数据并筛选').disabled
        press(app,'获取真实数据并筛选')
        assert not app.exception and not app.error
        assert 'result' in app.session_state

def test_failed_new_parse_is_explained_and_old_draft_can_be_restored():
    """失败状态不能留下无说明灰按钮；恢复旧草案必须显式操作并重新确认。"""
    with patch('core.intent_parser.parse_intent',side_effect=[draft(),ValueError('测试解析限额')]):
        app=AppTest.from_file(APP,default_timeout=20).run()
        app.text_area[0].set_value('PE大于0且不超过25');press(app,'让 AI 解析')
        app.text_area[0].set_value('新的需求');press(app,'让 AI 解析')
        app.checkbox[0].check().run()
        assert next(b for b in app.button if b.label=='获取真实数据并筛选').disabled
        assert any('测试解析限额' in w.value for w in app.warning)
        press(app,'放弃本次失败输入，恢复此前草案')
        assert not app.checkbox[0].value
        app.checkbox[0].check().run()
        assert not next(b for b in app.button if b.label=='获取真实数据并筛选').disabled
        assert not app.error and not app.exception
