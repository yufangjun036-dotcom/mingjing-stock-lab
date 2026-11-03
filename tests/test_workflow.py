"""工作流测试：澄清阻断、页面确认、真实客户端的替身集成。"""
import pytest
from pathlib import Path
from unittest.mock import patch
from core.intent_parser import IntentDraft, DraftCondition, draft_to_strategy
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize('field', ['clarifications','unsupported','refusal_reason'])
def test_blocked_draft(field):
    """模型有未解决事项时，不能执行其余部分条件。"""
    data = dict(conditions=[DraftCondition(metric_id='pe_ttm',operator='>',value='0')],
                assumptions=[],clarifications=[],unsupported=[],refusal_reason='')
    data[field] = '拒绝原因' if field == 'refusal_reason' else ['未解决事项']
    with pytest.raises(ValueError):
        draft_to_strategy(IntentDraft(**data))


def test_ui_confirm_and_result():
    """构造估值响应测试用户确认后取数、结果显示和原快照复用。"""
    envelope = {'endpoint':'/api/a-share/valuations/snapshot','request_id':'constructed-test',
                'retrieved_at':'2026-11-04T00:00:00+08:00','data':{'timestamp':1793721600000,'item':[
                    {'thscode':'600519.SH','name':'构造测试股票','pe_ttm':10,'pb_mrq':2}]}}
    with patch.dict('os.environ', {'FUYAO_API_KEY':'test-only'}), patch('data.provider.FuyaoClient.get_valuations', return_value=envelope) as fetch:
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=20).run()
        assert not app.exception
        assert next(b for b in app.button if b.label == '获取真实数据并筛选').disabled
        app.checkbox[0].check().run()
        next(b for b in app.button if b.label == '获取真实数据并筛选').click().run()
        assert not app.exception
        assert fetch.call_count == 1
        assert len(app.session_state['result'].rows) == 6
        assert sum(r.status == 'unknown' for r in app.session_state['result'].rows) == 5
        next(b for b in app.button if b.label == '使用原快照重算并比较').click().run()
        assert not app.exception
        assert fetch.call_count == 1
        assert app.session_state['changes'] == []
