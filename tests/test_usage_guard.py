"""用真实SQLite和线程验证限额；不消耗模型或金融API额度。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import pytest
from services.usage_guard import UsageGuard, UsageLimitError


def test_session_minute_limit_and_day_persistence(tmp_path):
    """按会话限流、文件重载保留日计数、跨天重置日额度。"""
    now=[1793721600.0]
    path=tmp_path/'usage.db';g=UsageGuard(path,daily=3,clock=lambda:now[0])
    for _ in range(2):
        with g.reserve('A'):pass
    with pytest.raises(UsageLimitError,match='每分钟'):
        with g.reserve('A'):pass
    with g.reserve('B'):pass
    other=UsageGuard(path,daily=3,clock=lambda:now[0])
    with pytest.raises(UsageLimitError,match='额度'):
        with other.reserve('C'):pass
    now[0]+=86400
    with other.reserve('A'):pass


def test_two_concurrent_slots_and_release_on_failure(tmp_path):
    """两个真实线程占槽时拒绝第三个，异常退出后可继续。"""
    g=UsageGuard(tmp_path/'usage.db');ready=Barrier(3);release=Event()
    def task(session):
        """持有槽直至主测试释放，避免凭睡眠猜并发状态。"""
        with g.reserve(session):
            ready.wait(timeout=5)
            release.wait(timeout=5)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(task,str(i)) for i in range(2)]
        try:
            ready.wait(timeout=5)
            with pytest.raises(UsageLimitError,match='正在执行'):
                with g.reserve('third'):pass
        finally:release.set()
        for job in jobs:job.result()
    with pytest.raises(RuntimeError):
        with g.reserve('failure'):raise RuntimeError('模拟调用失败')
    with g.reserve('next'):pass


def test_simultaneous_initialization_shares_one_guard():
    """多个会话首次进入时也必须共享同一组并发槽。"""
    from services.usage_guard import get_usage_guard
    with ThreadPoolExecutor(max_workers=8) as pool:
        guards=list(pool.map(lambda _:get_usage_guard(),range(16)))
    assert len({id(guard) for guard in guards})==1
