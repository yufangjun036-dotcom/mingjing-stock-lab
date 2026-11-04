"""重放线上误导说明的界面回归；使用替身，不冒充新模型调用。"""
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from tests.test_parse_recovery import APP, draft, press
from ui.intent_notes import MISSING_DATA_POLICY


def test_observed_missing_assumption_is_not_presented_as_policy():
    """保留实际观察的错误原句，同时展示准确规则且不改动条件。"""
    original = "缺失数据无法判定符合条件，视为不满足筛选条件。"
    value = draft()
    value.assumptions = [original, "低市盈率采用正值前提"]
    with patch('core.intent_parser.parse_intent', return_value=value):
        app = AppTest.from_file(APP).run()
        app.text_area[0].set_value('市盈率大于0且不超过25倍')
        press(app, '让 AI 解析')
        assert not app.exception
        assert any(item.value == MISSING_DATA_POLICY for item in app.info)
        assert not any(original in item.value for item in app.warning)
        assert any(item.value == original for item in app.text)
        assert any('正值前提' in item.value for item in app.warning)
        assert app.session_state['draft'].model_dump() == value.model_dump()
        assert next(b for b in app.button if b.label == '获取真实数据并筛选').disabled


def test_custom_missing_policy_remains_blocked():
    """用户要求缺失当零时，不能因说明调整而清除原有不支持事项。"""
    value = draft()
    value.unsupported = ['缺失值按0处理不受支持']
    with patch('core.intent_parser.parse_intent', return_value=value):
        app = AppTest.from_file(APP).run()
        app.text_area[0].set_value('市盈率小于25，缺失按0处理')
        press(app, '让 AI 解析')
        app.checkbox[0].check().run()
        assert not app.exception
        assert any('缺失值按0处理不受支持' in item.value for item in app.warning)
        assert next(b for b in app.button if b.label == '获取真实数据并筛选').disabled
