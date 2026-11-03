"""缓存与同时取数回归：构造数据只检验控制流程，不作为行情准确性证据。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import sleep
from unittest.mock import patch, MagicMock
from decimal import Decimal
from config import Settings
from tests.test_snapshot_union import FakeClient, make_strategy
from services.screening_service import fetch_snapshot, cached_screening
from services import snapshot_cache as cache
from ui.external_operation import run_external_operation


def test_ttl_scope_failure_and_threshold_reuse():
    """过期、凭据变更、缺指标均不命中；失败不缓存，门槛变化复用原数据。"""
    settings=Settings(fuyao_api_key='cache-test')
    s=make_strategy('pe_ttm');snapshot=fetch_snapshot(FakeClient(),s)
    key=cache.cache_key(cache.namespace(settings.fuyao_api_key),s)
    with patch.object(cache,'_CACHE',cache.OrderedDict()), patch.object(cache,'monotonic',return_value=100):
        cache.put_snapshot(key,snapshot)
        changed=s.model_copy(update={'conditions':(s.conditions[0].model_copy(update={'value':Decimal('20')}),)})
        assert cached_screening(settings,changed)[0].id==snapshot.id
        assert cached_screening(Settings(fuyao_api_key='different'),s) is None
        assert cached_screening(settings,make_strategy('volatility_60d')) is None
        with patch.object(cache,'monotonic',return_value=401):
            assert cache.get_snapshot(key) is None
        cache.put_snapshot(key,snapshot.model_copy(update={'source_errors':('测试失败',)}))
        assert cache.get_snapshot(key) is None


def test_two_cold_queries_share_fetch():
    """两个同时请求只进行一次底层取数，快照一致且彼此不共享可变对象。"""
    s=make_strategy('pe_ttm');snapshot=fetch_snapshot(FakeClient(),s)
    client=FakeClient();client.cache_namespace='parallel-test'
    barrier=Barrier(2)
    def slow(*a,**kw):
        sleep(.08)
        return snapshot
    def request():
        barrier.wait()
        return fetch_snapshot(client,s)
    with patch.object(cache,'_CACHE',cache.OrderedDict()), patch('services.screening_service._fetch_snapshot_uncached',side_effect=slow) as fetch:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:request(),range(2)))
        assert fetch.call_count==1
        assert results[0].id==results[1].id and results[0] is not results[1]


def test_warm_ui_avoids_client_and_quota():
    """有效缓存命中不调用外部操作、客户端或额度服务。"""
    factory,operation=MagicMock(),MagicMock()
    with patch('ui.external_operation.get_usage_guard') as guard, patch('ui.external_operation.st.caption'):
        assert run_external_operation(None,'test',factory,operation,cached_operation=lambda:('snapshot','result'))==('snapshot','result')
        factory.assert_not_called(); operation.assert_not_called(); guard.assert_not_called()
