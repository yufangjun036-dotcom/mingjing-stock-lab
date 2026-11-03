"""两个独立Streamlit测试会话的状态隔离，不使用外部API或真实用户隐私。"""
from pathlib import Path
from streamlit.testing.v1 import AppTest
from tests.test_core import snapshot,strategy
from core.screening_engine import screen


def test_two_sessions_do_not_share_draft_result_or_confirmation():
    """A的草案、结果、勾选不能出现在B；两者具有不同限流会话ID。"""
    path=Path(__file__).resolve().parents[1]/'app.py'
    a=AppTest.from_file(path,default_timeout=20).run()
    b=AppTest.from_file(path,default_timeout=20).run()
    assert a.session_state['usage_session'] != b.session_state['usage_session']
    a.session_state['conditions']=[{'metric_id':'pe_ttm','operator':'>','value':'99'}]
    a.session_state['editor_revision']+=1
    data=snapshot()
    a.session_state['snapshot']=data
    a.session_state['result']=screen(data,strategy(('>',99)))
    a.run()
    a.checkbox[0].check().run()
    b.run()
    assert not a.exception and not b.exception
    assert a.checkbox[0].value and not b.checkbox[0].value
    assert b.session_state['conditions'][0]['value']=='0'
    assert 'result' not in b.session_state
    assert 'snapshot' not in b.session_state
    # B显式切换方案后A的既有结果仍然保持，验证双向隔离。
    next(x for x in b.button if x.label=='切换为独立手动方案').click().run()
    a.run()
    assert a.session_state['result'].strategy.conditions[0].value==99
    assert a.session_state['conditions'][0]['value']=='99'
