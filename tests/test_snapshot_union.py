"""构造服务依赖验证新增指标比较和部分源失败；不调用外部接口。"""
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from unittest.mock import patch
import pytest
from core.schemas import Strategy, Condition, MetricValue
from core.screening_engine import screen
from data.provider import ProviderError
from services.screening_service import fetch_snapshot, run_screening, compare_with_new_snapshot


class FakeClient:
    """只提供构造响应的接口替身。"""
    def get_valuations(self, codes):
        """为固定股票池返回统一的正估值。"""
        return {'endpoint':'/constructed','request_id':'test','retrieved_at':'2026-11-04T00:00:00+08:00',
                'data':{'timestamp':1793721600000,'item':[{'thscode':c,'pe_ttm':10,'pb_mrq':1} for c in codes]}}

    def get_income(self, code):
        """模拟财务接口超时。"""
        raise ProviderError('timeout','构造测试超时')


def make_strategy(metric):
    """建立单条件方案。"""
    return Strategy(conditions=(Condition(id='c1',metric_id=metric,operator='>',value='0'),))


def test_partial_failure_preserves_universe():
    """一类数据失败后仍保留全部股票，且错误不能变成普通零入选。"""
    s=make_strategy('revenue_yoy')
    snapshot=fetch_snapshot(FakeClient(),s,now=datetime(2026,11,4,tzinfo=ZoneInfo('Asia/Shanghai')))
    assert len(snapshot.records)==6 and len(snapshot.source_errors)==6
    result=screen(snapshot,s)
    assert all(row.status=='unknown' for row in result.rows)


def test_missing_metric_and_union_recalculation():
    """原快照缺字段先阻断；联合快照同时重算 A/B 而非混合两个时点。"""
    a,b=make_strategy('pe_ttm'),make_strategy('revenue_yoy')
    snapshot=fetch_snapshot(FakeClient(),a)
    with pytest.raises(ValueError,match='新增指标'):
        run_screening(FakeClient(),b,snapshot)
    baseline=screen(snapshot,a)
    new_snapshot=fetch_snapshot(FakeClient(),b)
    with patch('services.screening_service.fetch_snapshot',return_value=new_snapshot) as fetch:
        current,old,new,changes=compare_with_new_snapshot(FakeClient(),baseline,b)
        assert fetch.call_args.kwargs['extra_strategy']==baseline.strategy
        assert old.snapshot_id==new.snapshot_id==current.id
        assert len(changes)==6 and all(c['after']=='unknown' for c in changes)
