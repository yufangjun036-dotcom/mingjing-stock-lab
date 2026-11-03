"""正式代码审查的行为回归；构造会话不冒充真实金融验收。"""
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from tests.test_core import snapshot, strategy
from core.screening_engine import screen
from data.provider import ProviderError
from core.intent_parser import IntentDraft

APP=Path(__file__).resolve().parents[1]/'app.py'


def test_manual_switch_requires_new_confirmation():
    """用户切换方案后旧勾选不能继续表示已确认新方案。"""
    app=AppTest.from_file(APP, default_timeout=20).run()
    app.checkbox[0].check().run()
    next(b for b in app.button if b.label=='切换为独立手动方案').click().run()
    assert not app.checkbox[0].value
    assert next(b for b in app.button if b.label=='获取真实数据并筛选').disabled


def test_changed_conditions_and_assumptions_reset_confirmation():
    """修改数字及新草案假设都需重新确认；相同上下文重跑不应清空。"""
    app=AppTest.from_file(APP, default_timeout=20).run()
    app.checkbox[0].check().run()
    app.run()
    assert app.checkbox[0].value
    app.session_state['conditions']=[{'metric_id':'pe_ttm','operator':'>','value':'10'}]
    app.session_state['editor_revision']+=1
    app.run()
    assert not app.checkbox[0].value
    app.checkbox[0].check().run()
    app.session_state['draft']=IntentDraft(conditions=[],assumptions=['新假设待确认'],clarifications=[],unsupported=[],refusal_reason='')
    app.run()
    assert not app.checkbox[0].value


def test_existing_snapshot_comparison_does_not_construct_client():
    """快照比较不应重新鉴权或创建网络客户端。"""
    data=snapshot();s=strategy(('>',0),('<',25))
    app=AppTest.from_file(APP, default_timeout=20).run()
    app.session_state['snapshot']=data
    app.session_state['result']=screen(data,s)
    app.run()
    app.checkbox[0].check().run()
    with patch('app.FuyaoClient',side_effect=ProviderError('configuration','测试禁止创建客户端')):
        # AppTest以脚本命名执行；patch原定义确保新导入也受约束。
        with patch('data.provider.FuyaoClient',side_effect=ProviderError('configuration','测试禁止创建客户端')) as client:
            next(b for b in app.button if b.label=='使用原快照重算并比较').click().run()
            assert client.call_count==0
    assert not app.exception
    assert not app.error
    assert app.session_state['changes']==[]
