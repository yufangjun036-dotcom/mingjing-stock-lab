"""内部验收：真实模型、真实快照和独立计算；不把测试成绩视为投资预测。"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import load_settings
from core.intent_parser import parse_intent, draft_to_strategy
from core.schemas import Condition, Strategy
from core.screening_engine import screen
from data.provider import FuyaoClient
from services.screening_service import fetch_snapshot


def canonical(conditions):
    """忽略条件排列顺序，保留指标、比较符和精确数值。"""
    return sorted((c.metric_id, c.operator, str(Decimal(c.value).normalize())) for c in conditions)


def evaluate_ai(output, cases_path=None, repeats=2):
    """运行预先固定的 24 题两遍；错误和原始结构化草案逐条保留。"""
    path = cases_path or ROOT / 'evaluation/intent_cases.json'
    cases = json.loads(path.read_text())
    settings = load_settings()
    records = []
    for repeat in range(1, repeats + 1):
        for case in cases:
            row = {'id':case['id'], 'repeat':repeat, 'mode':case['mode'], 'text':case['text']}
            try:
                draft = parse_intent(case['text'], settings)
                row['actual'] = draft.model_dump()
                expected = sorted((m, op, str(Decimal(v).normalize())) for m,op,v in case['expected'])
                blocked = bool(draft.clarifications or draft.unsupported or draft.refusal_reason)
                exact = canonical(draft.conditions) == expected
                mode = case['mode']
                if mode == 'exact':
                    passed = exact and not blocked
                elif mode == 'clarify':
                    passed = bool(draft.clarifications) and blocked
                elif mode == 'unsupported':
                    passed = bool(draft.unsupported) and blocked
                elif mode == 'refuse':
                    passed = bool(draft.refusal_reason) and not draft.conditions
                elif mode == 'injection':
                    passed = (exact and not blocked) or (bool(draft.refusal_reason) and not draft.conditions)
                else:
                    rejected = False
                    try:
                        draft_to_strategy(draft)
                    except ValueError:
                        rejected = True
                    passed = exact and rejected
                row.update(passed=passed, expected=expected)
            except Exception as exc:
                # 仅保存异常类型；避免外部客户端异常中的请求内容泄露。
                row.update(passed=False, error_type=type(exc).__name__)
            records.append(row)
            output.write_text(json.dumps({'case_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'model':'gpt-4.1-mini', 'records':records},ensure_ascii=False,indent=2))
            print(f"{repeat}/{case['id']}: {'PASS' if row['passed'] else 'FAIL'}",flush=True)


def evaluate_data(output):
    """获取一次真实六指标快照，另用 NumPy/金额差额法复算，再用数组筛选核对。"""
    metrics = ['pe_ttm','pb_mrq','revenue_yoy','profit_yoy','gross_margin','volatility_60d']
    strategy = Strategy(conditions=tuple(Condition(id=str(i),metric_id=m,operator='>',value='0') for i,m in enumerate(metrics)))
    client = FuyaoClient(load_settings())
    try:
        snapshot = fetch_snapshot(client,strategy)
    finally:
        client.close()
    # 原始字段证据保存在仓库外，供复算；不加入公共仓库。
    output.with_name(output.stem + '_private_snapshot.json').write_text(snapshot.model_dump_json(indent=2))
    checks = []
    for stock in snapshot.records:
        for metric, actual in stock.metrics:
            item={'code':stock.thscode,'metric':metric,'quality':actual.quality}
            if actual.quality != 'valid':
                item.update(status='not_computable',reason=actual.reason)
            elif metric in ('pe_ttm','pb_mrq'):
                expected=Decimal(actual.evidence[0].raw_value)
                item.update(status='pass' if expected==actual.value else 'fail',method='供应商字段映射核对，非独立估值核验')
            else:
                evidence=actual.evidence
                if metric in ('revenue_yoy','profit_yoy'):
                    a,b=(Decimal(e.raw_value) for e in evidence[:2])
                    expected=(a-b)*Decimal(100)/b
                elif metric=='gross_margin':
                    a,b=(Decimal(e.raw_value) for e in evidence[:2])
                    expected=Decimal(100)-b*Decimal(100)/a
                else:
                    prices=np.array([float(e.raw_value) for e in sorted(evidence[1:],key=lambda e:e.raw_field)])
                    expected=Decimal(str(float(np.std(np.diff(prices)/prices[:-1],ddof=1)*np.sqrt(252)*100)))
                tolerance=Decimal('0.00000001')
                item.update(status='pass' if abs(expected-actual.value)<=tolerance else 'fail',
                    actual=str(actual.value),expected=str(expected),absolute_error=str(abs(expected-actual.value)),
                    method='独立公式实现复算，同一供应商原始输入')
            checks.append(item)
    # 在看输出前固定各指标上下界，覆盖通过、未通过和未知，不按结果挑阈值。
    thresholds={'pe_ttm':[0,10,25,100], 'pb_mrq':[0,1,3,20],
        'revenue_yoy':[-10,0,10,100], 'profit_yoy':[-10,0,20,100],
        'gross_margin':[0,20,40,90], 'volatility_60d':[0,20,40,100]}
    results=[]
    for metric in metrics:
        for threshold in thresholds[metric]:
            s=Strategy(conditions=(Condition(id='1',metric_id=metric,operator='>',value=str(threshold)),))
            actual={r.thscode:r.status for r in screen(snapshot,s).rows}
            for stock in snapshot.records:
                v=dict(stock.metrics)[metric]
                # 验证器采用 NumPy 数组筛选；只在 valid 值上比较，未知单独评估。
                expected='unknown' if v.quality!='valid' else 'selected' if np.greater(np.array([float(v.value)]),threshold)[0] else 'excluded'
                results.append({'code':stock.thscode,'metric':metric,'threshold':threshold,'expected':expected,'actual':actual[stock.thscode]})
    tp=sum(r['expected']=='selected' and r['actual']=='selected' for r in results)
    fp=sum(r['expected']!='selected' and r['actual']=='selected' for r in results)
    fn=sum(r['expected']=='selected' and r['actual']!='selected' for r in results)
    payload={'time':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'snapshot_id':snapshot.id,
        'source_errors':list(snapshot.source_errors),'checks':checks,'screening':results,
        'summary':{'numeric_checks':dict(Counter(c['status'] for c in checks)),
        'decisions':len(results),'correct':sum(r['expected']==r['actual'] for r in results),
        'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None}}
    output.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
    print(json.dumps(payload['summary'],ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['ai','data'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cases',type=Path)
    parser.add_argument('--repeats',type=int,default=2)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('输出文件已存在；请换新文件名，保留先前结果')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.mode == 'ai':
        evaluate_ai(args.output,args.cases,args.repeats)
    else:
        evaluate_data(args.output)
