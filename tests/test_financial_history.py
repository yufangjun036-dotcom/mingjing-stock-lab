"""构造数据检验财务口径、交叉验证和历史窗口，非真实投资数据。"""
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
import pytest
from data.normalizer import normalize_financials, normalize_history, normalize_stock


def envelope(data):
    """构造带明确时间和请求标识的数据封套。"""
    return {'endpoint':'/constructed','request_id':'test','retrieved_at':'2026-11-04T00:00:00+08:00','data':data}


def inputs():
    """累计收入 120/100、归母利润 30/20、成本 60。"""
    rows=[]
    for year,revenue,profit in [(2026,120,30),(2025,100,20)]:
        rows.append({'thscode':'600519.SH','fiscal_year':year,'fiscal_period':'Q3','currency':'CNY','period':'quarterly',
                     'period_end_ms':int(datetime(year,9,30,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()*1000),
                     'operating_income':revenue,'operating_costs':60,'parent_holder_net_profit':profit})
    indicators={'thscode':'600519.SH','report':'2026-3','abilities':[{'indicators':[
        {'index_id':'calculate_operating_income_yoy_growth_ratio','value':'20'},
        {'index_id':'calculate_parent_holder_net_profit_yoy_growth_ratio','value':'50'},
        {'index_id':'sale_gross_margin','value':'50'}]}]}
    return envelope({'item':rows}),envelope(indicators)


def test_financial_values_and_evidence():
    """金额复算与给定的独立预期一致，输入和交叉源均可追溯。"""
    income,indicators=inputs()
    values=normalize_financials('600519.SH',income,indicators,'2026-3')
    assert [values[k].value for k in ['revenue_yoy','profit_yoy','gross_margin']] == [Decimal(20),Decimal(50),Decimal(50)]
    assert all(v.quality=='valid' and len(v.evidence)==3 for v in values.values())


def test_crosscheck_conflict():
    """供应商数字偏离复算值时阻止筛选。"""
    income,indicators=inputs()
    indicators['data']['abilities'][0]['indicators'][0]['value']='25'
    assert normalize_financials('600519.SH',income,indicators,'2026-3')['revenue_yoy'].quality=='conflict'
    assert normalize_financials('600519.SH',income,None,'2026-3')['profit_yoy'].quality=='unverified'


@pytest.mark.parametrize('mutation',['duplicate','currency','date','code'])
def test_report_conflicts(mutation):
    """报告重复、币种、期末和股票代码异常必须阻断。"""
    income,indicators=inputs()
    row=income['data']['item'][0]
    if mutation=='duplicate':income['data']['item'].append(dict(row))
    if mutation=='currency':row['currency']='USD'
    if mutation=='date':row['period_end_ms']=0
    if mutation=='code':row['thscode']='000001.SZ'
    assert all(v.quality=='conflict' for v in normalize_financials('600519.SH',income,indicators,'2026-3').values())


def test_history_evidence_and_calendar():
    """构造日历不依赖周一至周五假设；60 收益率对应 61 个价格。"""
    dates=[date(2026,8,1)+timedelta(days=i) for i in range(61)]
    ms=lambda d:int(datetime(d.year,d.month,d.day,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()*1000)
    cal=envelope({'item':[{'date_ms':ms(d),'date':d.strftime('%Y%m%d')} for d in dates]})
    history=envelope({'adjust':'forward','interval':'1d','item':[{'date_ms':ms(d),'close_price':100} for d in dates]})
    value=normalize_history(history,cal,dates[-1])
    assert value.value==0 and value.quality=='valid' and len(value.evidence)==62
    history['data']['item'].pop(20)
    assert normalize_history(history,cal,dates[-1]).quality=='missing'
    cal['data']['item'][0]['date']='20990101'
    assert normalize_history(history,cal,dates[-1]).quality=='conflict'


def test_stale_batch():
    """过旧批次和时间缺失不能标为正常估值。"""
    data=envelope({'timestamp':0,'item':[{'thscode':'600519.SH','pe_ttm':10,'pb_mrq':2}]})
    assert dict(normalize_stock('600519.SH',data).metrics)['pe_ttm'].quality=='stale'
    data['data']['timestamp']=None
    assert dict(normalize_stock('600519.SH',data).metrics)['pe_ttm'].quality=='unverified'
