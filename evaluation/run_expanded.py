"""30 股票真实接口扩测：独立评测范围，不改动产品股票池；原始响应留本地。"""
import sys,json,hashlib,csv
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from config import load_settings
from data.provider import FuyaoClient,ProviderError
from data.normalizer import normalize_stock,normalize_financials,normalize_history
from core.schemas import StockRecord,Condition,Strategy
from core.screening_engine import evaluate_stock


def main():
    """冻结计划、取真实响应、留档、独立复算和逐股比对；所有失败保留。"""
    dest=Path(sys.argv[1]);dest.mkdir(parents=True,exist_ok=False)
    plan_path=ROOT/'evaluation/expanded_plan.json'
    plan=json.loads(plan_path.read_text());(dest/'plan.json').write_bytes(plan_path.read_bytes())
    now=datetime.now(ZoneInfo('Asia/Shanghai'));cutoff=now.date()-timedelta(days=1);start=cutoff-timedelta(days=220)
    client=FuyaoClient(load_settings())
    valuation=client.get_valuations(plan['codes']);calendar=client.get_calendar(start,cutoff)
    (dest/'private_base.json').write_text(json.dumps({'valuation':valuation,'calendar':calendar},ensure_ascii=False))
    def fetch(code):
        """每股票顺序读取，最多两股票并发；先保存原响应再标准化。"""
        raw={};errors=[]
        for key,call in [('income',lambda:client.get_income(code)),('indicators',lambda:client.get_indicators(code,'2026-3')),('history',lambda:client.get_history(code,start,cutoff))]:
            try:raw[key]=call()
            except ProviderError as exc:errors.append(str(exc))
        (dest/f'private_{code}.json').write_text(json.dumps(raw,ensure_ascii=False))
        stock=normalize_stock(code,valuation);values=dict(stock.metrics)
        if 'income' in raw:values.update(normalize_financials(code,raw['income'],raw.get('indicators'),'2026-3'))
        if 'history' in raw:values['volatility_60d']=normalize_history(raw['history'],calendar,cutoff)
        print(code+' fetched',flush=True)
        return StockRecord(thscode=code,name=stock.name,metrics=tuple(values.items())),raw,errors
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:collected=list(pool.map(fetch,plan['codes']))
    finally:client.close()
    checks=[];decisions=[]
    for stock,raw,errors in collected:
        values=dict(stock.metrics);independent={}
        # 独立预期直接读取真实响应，不读取产品已经计算出的数值生成答案。
        rows=raw.get('income',{}).get('data',{}).get('item',[])
        pair=[[r for r in rows if r.get('fiscal_year')==year and r.get('fiscal_period')=='Q3'] for year in (2026,2025)]
        if all(len(r)==1 for r in pair):
            a,b=pair[0][0],pair[1][0]
            for metric,field in [('revenue_yoy','operating_income'),('profit_yoy','parent_holder_net_profit')]:
                if a.get(field) is not None and b.get(field) is not None and Decimal(str(b[field]))>0:
                    independent[metric]=(Decimal(str(a[field]))-Decimal(str(b[field])))*100/Decimal(str(b[field]))
            if a.get('operating_income') and a.get('operating_costs') is not None:
                independent['gross_margin']=100-Decimal(str(a['operating_costs']))*100/Decimal(str(a['operating_income']))
        matches=[r for r in valuation['data']['item'] if r.get('thscode')==stock.thscode]
        if len(matches)==1:
            for m in ('pe_ttm','pb_mrq'):
                if matches[0].get(m) is not None:independent[m]=Decimal(str(matches[0][m]))
        days=sorted(r['date_ms'] for r in calendar['data']['item'])[-61:]
        bars=raw.get('history',{}).get('data',{}).get('item',[])
        prices={r['date_ms']:r.get('close_price') for r in bars}
        if len(days)==61 and all(prices.get(d) and prices[d]>0 for d in days):
            arr=np.array([prices[d] for d in days],dtype=float)
            independent['volatility_60d']=Decimal(str(float(np.std(np.diff(arr)/arr[:-1],ddof=1)*np.sqrt(252)*100)))
        for metric,thresholds in plan['thresholds'].items():
            actual=values.get(metric);expected=independent.get(metric)
            status='not_verified'
            if actual and actual.quality=='valid' and expected is not None:status='pass' if abs(actual.value-expected)<=Decimal('1e-8') else 'fail'
            sources=[]
            for e in actual.evidence if actual else []:
                sources.append({'endpoint':e.endpoint,'request_id':e.request_id,'retrieved_at':e.retrieved_at,'field':e.raw_field})
            checks.append({'code':stock.thscode,'name':stock.name,'metric':metric,'quality':actual.quality if actual else 'missing','actual':str(actual.value) if actual and actual.value is not None else None,'expected':str(expected) if expected is not None else None,'status':status,'reason':actual.reason if actual else ';'.join(errors),'sources':sources,'basis':'供应商原字段映射' if metric in ('pe_ttm','pb_mrq') else '同次原始响应独立公式复算，非公告独立审计'})
            # 非有效项不进入准确率分母，避免把产品自己的质量标签充当正确答案。
            if status=='pass':
                for threshold in thresholds:
                    strategy=Strategy(conditions=(Condition(id='1',metric_id=metric,operator='>',value=threshold),))
                    result=evaluate_stock(stock,strategy)
                    wanted='selected' if expected>Decimal(threshold) else 'excluded'
                    decisions.append({'code':stock.thscode,'metric':metric,'threshold':threshold,'expected':wanted,'actual':result.status,'passed':wanted==result.status})
    tp=sum(r['expected']==r['actual']=='selected' for r in decisions);fp=sum(r['expected']!='selected' and r['actual']=='selected' for r in decisions);fn=sum(r['expected']=='selected' and r['actual']!='selected' for r in decisions)
    report={'time':now.isoformat(),'plan_sha256':hashlib.sha256(plan_path.read_bytes()).hexdigest(),'stocks':len(collected),'source_errors':{s.thscode:e for s,r,e in collected if e},'checks':checks,'decisions':decisions,'summary':{'pass':sum(c['status']=='pass' for c in checks),'fail':sum(c['status']=='fail' for c in checks),'not_verified':sum(c['status']=='not_verified' for c in checks),'decisions':len(decisions),'correct':sum(r['passed'] for r in decisions),'tp':tp,'fp':fp,'fn':fn}}
    (dest/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report['summary'],ensure_ascii=False),flush=True)


if __name__=='__main__':main()
