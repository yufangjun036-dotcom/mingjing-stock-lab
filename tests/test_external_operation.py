"""可控阻塞模拟验证超时，不将模拟耗时计为供应商真实性能。"""
from contextlib import contextmanager
from threading import Event
from time import monotonic
from unittest.mock import MagicMock, patch
import pytest
from config import Settings
from data.provider import FuyaoClient, ProviderError
from ui.external_operation import run_external_operation


def test_timeout_keeps_slot_until_worker_finishes_and_discards_late_result():
    """超时立即返回页面，但后台结束前不释放保护，也不提前关闭在途连接。"""
    entered, release, closed, exited = Event(), Event(), Event(), Event()
    client = MagicMock()
    client.close.side_effect = closed.set
    @contextmanager
    def reserve(_):
        """记录测试任务占用和释放并发槽的生命周期。"""
        try:
            entered.set()
            yield
        finally:
            exited.set()
    guard = MagicMock(); guard.reserve.side_effect = reserve
    def blocked(c):
        """构造受阻任务以验证超时后的资源管理。"""
        release.wait(2)
        return '迟到结果'
    try:
        with patch('ui.external_operation.get_usage_guard',return_value=guard), patch('ui.external_operation.st.empty',return_value=MagicMock()):
            start = monotonic()
            with pytest.raises(ProviderError, match='超过0.05秒'):
                run_external_operation(None,'test',lambda _:client,blocked,timeout=.05)
            assert monotonic()-start < .5
            assert entered.is_set() and not exited.is_set()
            assert client.cancel_event.is_set() and not closed.is_set()
    finally:
        release.set()
    assert exited.wait(1) and closed.is_set()


def test_cancelled_provider_never_sends_next_request():
    """已取消任务不会继续消耗后续端点请求。"""
    client = FuyaoClient(Settings(fuyao_api_key='test-only'))
    client.cancel_event = Event(); client.cancel_event.set()
    try:
        with patch.object(client.client, 'get') as request:
            with pytest.raises(ProviderError,match='已取消'):
                client.get_valuations(['600519.SH'])
            request.assert_not_called()
    finally:
        client.close()
