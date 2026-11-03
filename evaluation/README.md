# 扩展验收复现

## 真实金融数据

`expanded_plan.json` 在取数前固定30只股票、阈值与选样规则。它是便利样本，不是全市场随机抽样。产品股票池仍是 data/universe.json 中的6只，扩测不改变产品能力宣传。

执行：`.venv/bin/python evaluation/run_expanded.py ../expanded_new_run`。目标目录须不存在，防止覆盖历史。脚本获取扶摇真实响应并先写本地，再标准化计算；最大两个股票任务并发。需要已配置 FUYAO_API_KEY。执行会产生实际API使用量。

原始 `private_*.json` 仅保留在仓库外。报告的 `sources` 提供原字段与请求编号。估值仅核对原字段映射；财务差额公式和 NumPy 波动率用于独立实现复算，不是另一数据供应商或原始公告审计。

`run_expanded.main`：读取冻结计划→取估值/日历→两线程逐股取财报/指标/价格→落地原始响应→运行产品标准化→从原始响应另算预期→记录每项差异→只对已核对有效值做单条件比较→生成 report.json。

内部 `fetch`：顺序请求同股三个端点，记录安全错误；持久化原响应后调用产品标准化，返回股票对象、原响应、错误清单。整个批次的估值/日历失败会使脚本失败，不生成成功报告。

## 真实模型评测

`intent_cases_100.json` 有100条不同文字的设计任务：24条原始案例、76条模板扩展。不是100条真实用户日志，也不是100个不同语义类别；语义覆盖有限。

70条 development、30条 holdout。留出集未调用，但与开发集共享生成模板，且由同一AI编写；不得称为外部独立盲测。下一阶段应由人审核预期答案并补充真实用户语料（经授权、去隐私）。

执行：`.venv/bin/python evaluation/run_acceptance.py ai --cases evaluation/intent_development_70.json --repeats 1 --output ../expanded_new_ai.json`。需要模型密钥，会产生真实模型调用。本地按需配置 OPENAI_PROXY；云端不得复制 localhost 代理。结果每题增量落盘，不覆盖已有结果文件。

预期条件来自数学比较语义和 core/metrics.py 白名单，非金融API提供。首次注入题E23判定规则存在安全处理路径遗漏，仍保留原判定，不事后改成通过。所有比例仅说明指定版本和指定测试集表现。
