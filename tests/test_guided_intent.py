"""新手引导的行为回归；全部为构造选择，不属于金融真实数据评测。"""
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from core.guided_intent import build_guided_draft


def test_selected_scope():
    """不添加用户未选择的约束，明确未覆盖原意。"""
    d=build_guided_draft('收入增加','暂不筛估值','暂不筛波动')
    assert [(c.metric_id,c.operator,c.value) for c in d.conditions]==[('revenue_yoy','>','0')]
    assert '本次未筛估值' in d.assumptions[1]
    assert '本次未筛波动' in d.assumptions[2]


def test_explicit_examples_and_custom_values():
    """教学数值标注性质；自定义数字保持原值。"""
    d=build_guided_draft('收入和利润都增加','教学示例','教学示例')
    assert len(d.conditions)==5
    assert '不是行业标准' in d.assumptions[1]
    assert '不是安全标准' in d.assumptions[2]
    d=build_guided_draft('利润增加','自定上限','自定上限','18.5','22.4')
    assert [c.value for c in d.conditions]==['0','0','18.5','22.4']


@pytest.mark.parametrize('args',[
    (None,'教学示例','教学示例'),
    ('收入增加','同行比较','暂不筛波动'),
    ('暂不筛经营变化','暂不筛估值','暂不筛波动'),
    ('收入增加','自定上限','暂不筛波动','NaN'),
    ('收入增加','自定上限','暂不筛波动','-5'),
    ('收入增加','自定上限','暂不筛波动',''),
    ('收入增加','暂不筛估值','自定上限','','Infinity'),
])
def test_invalid_or_unresolved_choices(args):
    """未选、不支持、空条件或无效阈值均拒绝生成。"""
    with pytest.raises(ValueError): build_guided_draft(*args)


def button(app,label):
    """按可见名称找到操作按钮。"""
    return next(b for b in app.button if b.label==label)


def test_guided_workflow_confirmation():
    """进入引导后不能执行；应用或修改选择后必须重新确认。"""
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=20).run()
    app.checkbox[0].check().run()
    button(app,'不懂指标？从三个常见想法开始').click().run()
    assert not app.exception
    assert all(r.value is None for r in app.radio)
    assert button(app,'把这些选择生成条件').disabled
    assert not any(b.label=='获取真实数据并筛选' for b in app.button)
    app.radio[0].set_value('收入和利润都增加').run()
    app.radio[1].set_value('暂不筛估值').run()
    app.radio[2].set_value('暂不筛波动').run()
    button(app,'把这些选择生成条件').click().run()
    assert not app.exception
    assert len(app.session_state['conditions'])==2
    assert any('无需复制回输入框' in x.value for x in app.success)
    assert not any('当前草案来源' in x.value for x in app.info)
    assert any(e.label=='查看原始描述（输入记录，不是解析结果）' for e in app.expander)
    assert not app.checkbox[0].value
    assert button(app,'获取真实数据并筛选').disabled
    app.checkbox[0].check().run()
    button(app,'不懂指标？从三个常见想法开始').click().run()
    app.radio[0].set_value('利润增加').run()
    button(app,'把这些选择生成条件').click().run()
    assert len(app.session_state['conditions'])==1
    assert not app.checkbox[0].value


def test_cancel_preserves_previous_conditions():
    """取消引导不能改变旧条件。"""
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=20).run()
    old=list(app.session_state['conditions'])
    button(app,'不懂指标？从三个常见想法开始').click().run()
    app.radio[0].set_value('利润增加').run()
    button(app,'返回原方案，不应用这些选择').click().run()
    assert not app.exception
    assert app.session_state['conditions']==old
