"""真实扶摇小样本性能复测：不调用模型、不保存密钥、不替代多人持续负载测试。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
from time import monotonic
from threading import Lock, Barrier
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from config import load_settings
from data.provider import FuyaoClient
from core.schemas import Strategy,Condition
from services.screening_service import run_screening,cached_screening
from services.usage_guard import get_usage_guard
from services import snapshot_cache as cache


def main():
    """测一次冷查询、三次暖查询、三次同快照计算及两会话同时冷查询。"""
    settings=load_settings(); calls=[]; lock=Lock(); results=[]
    strategy=Strategy(conditions=tuple(Condition(id=f'c{i}',metric_id=m,operator=o,value=v) for i,(m,o,v) in enumerate([
        ('pe_ttm','>',0),('pe_ttm','<=',25),('pb_mrq','>',0),('pb_mrq','<=',3),
        ('revenue_yoy','>=',5),('profit_yoy','>',10),('gross_margin','>=',20),('volatility_60d','<=',30)])))
    class MeasuredClient(FuyaoClient):
        """仅统计实际网络请求数量，不记录响应或鉴权头。"""
        def _request_json(self,path,params):
            """统计一次实际接口请求，随后调用真实客户端。"""
            with lock: calls.append(path)
            return super()._request_json(path,params)
    def cold(session):
        """在调用额度内执行冷查询，并确保释放客户端。"""
        started=monotonic()
        with get_usage_guard().reserve(session):
            client=MeasuredClient(settings)
            try: snapshot,result=run_screening(client,strategy)
            finally: client.close()
        return snapshot,result,monotonic()-started
    def record(label,snapshot,result,seconds,requests):
        """保存耗时、请求数量与快照标识，不保存密钥。"""
        results.append(dict(case=label,seconds=round(seconds,4),network_requests=requests,snapshot_id=snapshot.id,
                            selected=sum(r.status=='selected' for r in result.rows),source_errors=list(snapshot.source_errors)))
    snapshot,result,elapsed=cold('perf-cold-'+datetime.now().isoformat());record('cold',snapshot,result,elapsed,len(calls))
    for i in range(3):
        count=len(calls);started=monotonic();s,r=cached_screening(settings,strategy)
        record('warm-'+str(i+1),s,r,monotonic()-started,len(calls)-count)
    for i in range(3):
        count=len(calls);started=monotonic();s,r=run_screening(None,strategy,snapshot)
        record('same-snapshot-'+str(i+1),s,r,monotonic()-started,len(calls)-count)
    with cache._LOCK:cache._CACHE.clear()
    count=len(calls);barrier=Barrier(2)
    def concurrent(i):
        """等待两个测试线程就绪后同时开始查询。"""
        barrier.wait()
        return cold('perf-parallel-'+str(i)+'-'+datetime.now().isoformat())
    with ThreadPoolExecutor(max_workers=2) as pool: parallel=list(pool.map(concurrent,range(2)))
    for i,(s,r,t) in enumerate(parallel):record('parallel-'+str(i+1),s,r,t,None)
    output={'created_at':datetime.now().isoformat(),'scope':'本地服务层；不是浏览器端到端或持续负载测试',
            'results':results,'parallel_total_requests':len(calls)-count,'total_requests':len(calls)}
    Path(sys.argv[1]).write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps(output,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
