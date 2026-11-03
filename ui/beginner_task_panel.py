"""先完成一次研究任务，再按需进入专业编辑；所有联网仍由明确按钮触发。"""
import streamlit as st
from pydantic import ValidationError
from core.beginner_task import growth_strategy, beginner_rows
from core.schemas import DatasetSnapshot, ScreeningResult
from data.provider import FuyaoClient, ProviderError
from services.screening_service import run_screening, compare_results, cached_screening
from services.usage_guard import get_usage_guard
from ui.results_panel import render_results
from ui.external_operation import run_external_operation


def render_beginner_task(settings):
    """展示任务、真实查询及同快照比较；独立状态不覆盖用户的专业方案。"""
    st.subheader('第一次用？先完成这件事')
    st.markdown('### 哪些公司的收入和利润，比去年同期增加了？')
    st.write('点击后，我会查询六家公司的真实财务数据，告诉你每家公司是否符合这两个条件，并解释原因。你不用填写指标或数字。')
    st.caption('查看范围：平安银行、万科、宁德时代、招商银行、贵州茅台、长江电力。比较2026年1–9月与2025年同期；这是研究练习，不代表值得买，也不代表持续增长。')
    with st.expander('我想先看看具体规则'):
        st.write('收入同比 > 0%，并且归属于母公司股东的净利润同比 > 0%。收入是经营取得的收入，利润还需要考虑成本等因素。两项必须同时增加。')
        st.write('不检查估值或价格波动。上年基数非正、数据缺失或冲突时不按普通同比强行判断。')
    # 热重载时重建类型，保持与现有主流程相同的数据契约。
    for key, model in [('task_snapshot', DatasetSnapshot), ('task_result', ScreeningResult)]:
        if key in st.session_state:
            st.session_state[key] = model.model_validate_json(st.session_state[key].model_dump_json())
    if st.button('开始查看：收入和利润是否都增加', type='primary', key='task_fetch'):
        try:
            snapshot, result = run_external_operation(
                settings, st.session_state['usage_session'], FuyaoClient,
                lambda client: run_screening(client, growth_strategy()),
                cached_operation=lambda: cached_screening(settings, growth_strategy()))
            st.session_state['task_snapshot'] = snapshot
            st.session_state['task_result'] = result
            st.session_state['task_income_only'] = False
            st.session_state['task_changes'] = None
            st.session_state['task_error'] = None
        except ValidationError:
            st.session_state['task_error'] = '数据校验未通过。本次未生成结果；下方如有结果，是上次查询保留的结果。'
        except (ProviderError, ValueError) as exc:
            # 服务层只提供经过处理的可公开错误，限额与缺密钥原因必须保留。
            st.session_state['task_error'] = f'{exc}。本次未生成结果；下方如有结果，是上次查询保留的结果。'
    if st.session_state.get('task_error'):
        st.error(st.session_state['task_error'])
    if 'task_result' not in st.session_state:
        st.info('下一步：点击上面的“开始查看”。现在还没有查询，也没有生成股票结论。')
        return
    snapshot = st.session_state['task_snapshot']
    result = st.session_state['task_result']
    st.subheader('查询结果：先看这张表')
    # 比较按钮本身明确描述变化；点击即确认比较，不额外联网。
    if st.button('如果只要求收入增加，结果会怎样？', key='task_compare'):
        _, result = run_screening(None, growth_strategy(True), snapshot)
        _, base = run_screening(None, growth_strategy(), snapshot)
        st.session_state['task_changes'] = compare_results(base, result)
        st.session_state['task_result'] = result
        st.session_state['task_income_only'] = True
    if st.session_state.get('task_income_only'):
        st.info('现在只要求收入增加，已取消“利润也增加”的要求。使用同一份数据，没有重新取数。')
        changes = st.session_state.get('task_changes') or []
        names = {r.thscode:r.name for r in result.rows}
        added = [names[c['thscode']] for c in changes if c['after']=='selected']
        st.write('新增符合条件的公司：' + ('、'.join(added) if added else '没有'))
        st.caption('新增符合条件不代表利润也在增长；请看表里的利润变化。')
    else:
        st.write('本次要求：收入和利润都比去年同期增加。')
    counts = {s:sum(r.status==s for r in result.rows) for s in ('selected','excluded','unknown')}
    st.write(f"六家公司中，{counts['selected']}家符合条件，{counts['excluded']}家不符合，{counts['unknown']}家暂不能确定。")
    for error in snapshot.source_errors:
        st.warning(error)
    st.dataframe(beginner_rows(snapshot,result), hide_index=True, use_container_width=True)
    st.caption(f'取数时间：{snapshot.created_at}；快照：{snapshot.id[:12]}。减少或持平不满足“增加”；某项已不满足时，即使另一项未知，也不会入选。百分数显示保留两位，判断使用未舍入值。')
    with st.expander('为什么这样判断？查看数字、来源和详细证据'):
        render_results(result,snapshot,key_prefix="beginner")
    st.write('下一步：可以点击“如果只要求收入增加，结果会怎样？”体验条件变化；想研究自己的问题，使用下方需求输入框。')
