"""单实例演示额度保护；SQLite保存计数，信号量约束进程内并发。"""
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore, Lock
from zoneinfo import ZoneInfo


class UsageLimitError(ValueError):
    """额度或并发不足时拒绝外部调用，向用户显示可理解的原因。"""


class UsageGuard:
    """同一持久化文件共享日额度；只支持一个服务进程的并发控制。"""
    def __init__(self, path, daily=100, per_minute=2, concurrent=2, clock=time.time):
        """建立计数库；参数可注入以验证真实锁和额度行为，不发起外部请求。"""
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.daily,self.per_minute,self.clock=daily,per_minute,clock
        self.slots=BoundedSemaphore(concurrent)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS daily (day TEXT PRIMARY KEY, count INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events (session TEXT NOT NULL, ts REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS event_session ON events(session,ts)')

    @contextmanager
    def reserve(self, session):
        """先占并发槽，再原子检查/计数；已发起尝试失败也计数，最后必释放槽。"""
        if not self.slots.acquire(blocking=False):
            raise UsageLimitError('当前已有两个外部操作正在执行，请稍后再试')
        try:
            now=self.clock()
            day=datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai')).date().isoformat()
            try:
                with sqlite3.connect(self.path,timeout=5) as db:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('DELETE FROM events WHERE ts <= ?', (now-60,))
                    count=db.execute('SELECT COUNT(*) FROM events WHERE session=?',(session,)).fetchone()[0]
                    used=db.execute('SELECT count FROM daily WHERE day=?',(day,)).fetchone()
                    if count>=self.per_minute:
                        raise UsageLimitError('本会话每分钟最多两个外部操作，请稍后再试')
                    if used and used[0]>=self.daily:
                        raise UsageLimitError('本演示今日100次外部操作额度已用完，请明日再试')
                    db.execute('INSERT INTO daily(day,count) VALUES (?,1) ON CONFLICT(day) DO UPDATE SET count=count+1',(day,))
                    db.execute('INSERT INTO events(session,ts) VALUES (?,?)',(session,now))
            except sqlite3.Error:
                # 计数不可用时拒绝请求，不绕过额度；不回显数据库路径或异常详情。
                raise UsageLimitError('调用计数服务暂不可用，本次未发起外部请求') from None
            yield
        finally:
            self.slots.release()


_INITIALIZE_LOCK = Lock()


@lru_cache(maxsize=1)
def _cached_guard(path):
    """缓存单实例保护器；只能在初始化锁内调用，避免同时首次访问创建多个信号量。"""
    return UsageGuard(path)


def get_usage_guard():
    """同一Python进程共用保护器；云端须提供持久化计数盘以跨实例重建保留日额度。"""
    default=Path(__file__).resolve().parents[1]/'.runtime/usage.sqlite3'
    try:
        with _INITIALIZE_LOCK:
            return _cached_guard(str(os.getenv('USAGE_DB_PATH') or default))
    except (OSError, sqlite3.Error):
        raise UsageLimitError('调用计数服务暂不可用，本次未发起外部请求') from None
