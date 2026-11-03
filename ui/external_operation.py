"""外部操作的有界等待：后台负责连接生命周期，页面仅消费安全进度。"""
from queue import Queue, Empty
from threading import Event, Thread
from time import monotonic
import streamlit as st
from data.provider import ProviderError
from services.usage_guard import get_usage_guard


def run_external_operation(settings, session_id, client_factory, operation, timeout=45, cached_operation=None):
    """到期放弃本轮结果；在途请求结束前继续占用并发名额，禁止后台改会话。"""
    if cached_operation is not None:
        cached = cached_operation()
        if cached is not None:
            st.caption('复用五分钟内采集的数据，本次未请求外部接口；采集时间见结果。')
            return cached
    messages = Queue()
    cancelled = Event()
    started = monotonic()

    def worker():
        """仅传递结果与安全消息，不在工作线程中调用Streamlit。"""
        client = None
        try:
            with get_usage_guard().reserve(session_id):
                try:
                    client = client_factory(settings)
                    client.cancel_event = cancelled
                    client.progress_callback = lambda message: messages.put(('progress', message))
                    result = operation(client)
                    if not cancelled.is_set():
                        messages.put(('result', result))
                finally:
                    if client is not None:
                        client.close()
        except Exception as exc:
            messages.put(('error', exc))

    Thread(target=worker, daemon=True, name='screening-operation').start()
    progress = st.empty()
    current = '准备连接数据服务'
    try:
        while True:
            elapsed = monotonic() - started
            if elapsed >= timeout:
                raise ProviderError('deadline', f'本次取数超过{timeout:g}秒，已停止等待且不会保存本轮结果。请稍后再试；在途请求结束前仍占用并发名额。')
            progress.info(f'{current} · 已等待{elapsed:.0f}秒 / 最多{timeout:g}秒')
            try:
                kind, value = messages.get(timeout=min(0.2, timeout-elapsed))
            except Empty:
                continue
            if kind == 'result':
                return value
            if kind == 'error':
                raise value
            current = value
    finally:
        # 页面重跑/超时也取消后续请求；迟到结果从不写入session_state。
        cancelled.set()
        progress.empty()
