# EvoRetail-Agent 实测缺陷根因定位与工业级优化方案

> **编制日期**：2026-10-27  
> **文档状态**：待审阅确认（确认后执行代码修改与自动化回归验证）  
> **编制依据**：基于 6 轮真实前端多轮对话测试日志与 `backend/` 源码逐行交叉取证。

---

## 一、 实测 6 轮对话暴露的 5 大核心根因（源码级定位）

通过对实测日志中全部异常现象的逆向追踪，定位出以下 **5 个确定性代码缺陷**：

### 根因 1：`OutputGuardrail` 单品参数全局强行覆写（导致“全员 ¥6999 / 2.3kg / 140W”及算术逻辑崩塌）
- **源码位置**：[`backend/api/v1/chat.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/api/v1/chat.py#L108-L175)、[`backend/guardrails/output_guard.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/guardrails/output_guard.py#L115-L235)
- **复现链路**：
  1. 前端默认选中商品卡片为 `HP-VICTUS-16`（HP 光影精灵 16：官方价 `¥6999`、裸机重 `2.3kg`、功耗 `140W`、刷新率 `240Hz`、`双 M.2 插槽`），每次请求均携带 `spu_code="HP-VICTUS-16"`。
  2. `chat.py` 无条件将 `product=ProductItem(HP-VICTUS-16)` 传入 `output_guardrail.guard_text()`。
  3. 当买家进行**跨机型对比**（第 2、6 轮）、**咨询其他机型**（第 3 轮问星 Book Pro 14）或**按预算筛选推荐**（第 4、5 轮）时，大模型或工具实际输出了正确的各机型参数（如战 66 售价 `¥4299`、重 `1.7kg`、功耗 `45W`；星 Book Pro 14 售价 `¥5499`、重 `1.4kg`；暗影精灵 10 Pro 售价 `¥12999`、功耗 `175W`）。
  4. 但流式输出经过 `OutputGuardrail.check_numeric_consistency()` 时，护栏把整篇回复里的**所有价格、重量、功耗、M.2 插槽描述**全部当成 `HP-VICTUS-16` 的参数进行正则硬替换：
     - 将 `¥4299`、`¥4599`、`¥5499`、`¥12999`、`¥7499` 全部强行替换为 `¥6999`，而未带 `¥` 符号的差价文本（如“差价为 2700 元”、“多出的 499 元”、“超出您预算约 5000 元”）未被正则匹配，直接造成**“两款都是 ¥6999 但差价 2700 元”、“预算 5000 推荐 ¥6999 还声称省下预算”**的严重逻辑崩塌；
     - 将 `1.7kg`、`1.4kg` 以及重量差值 `0.6kg`、`0.15kg` 全部被 `\d+(?:\.\d+)?\s*kg` 正则强行替换为 `2.3kg`，造成**“战 99 重 2.2kg，比暗影精灵轻 2.3kg”**（`0.2kg` 误差阈值放过了 `2.2kg`，却把 `0.15kg` 替换成了 `2.3kg`）；
     - 将核显的 `45W` 与雷电接口的 `100W PD 快充` 全部替换为 `140W`；
     - 将星 Book Pro 14 的 `单 M.2 插槽（仅支持替换升级）` 中的 `单 M.2` 局部替换为 `双 M.2 插槽（支持加装第二根固态）`，拼出病句 `双 M.2 插槽（支持加装第二根固态） 插槽（仅支持替换升级）`。

### 根因 2：`chat.py` 流式缓冲 40 字符硬截断腰斩数字（导致 `2240Hz` 荒谬参数）
- **源码位置**：[`backend/api/v1/chat.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/api/v1/chat.py#L150-L162)、[`backend/guardrails/output_guard.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/guardrails/output_guard.py#L41)
- **复现链路**：
  1. `CLAUSE_DELIMITERS` 仅按 `([，。！？；\n\r])` 切分。当大模型输出 Markdown 表格行 `| **屏幕刷新率** | 16.1 英寸 2.5K（2560×1440）**240Hz** | ...` 时，行内没有中文句末标点。
  2. 该行从 `|` 到 `**2` 恰好满 **40 个字符**！`chat.py` 第 151 行 `clause = buffer[:40]` 直接将 `**240Hz**` 从中间劈开：前半段输出 `...**2`，后半段剩余 `40Hz** | ...`。
  3. 后半段进入 `OutputGuardrail` 时，正则 `(\d{2,3})\s*Hz` 匹配到了 `40Hz`，判定与 `240Hz` 冲突，将 `40Hz` 替换为 `240Hz`。
  4. 前后端流式拼接后，前半段的 `**2` 与后半段替换后的 `240Hz**` 合体变成了 **`**2240Hz**`**。

### 根因 3：型号别名表与模糊解析对空格敏感 + 商品标题代际错位（导致“暗影精灵 16 Slim”被张冠李戴为“暗影精灵 10 旗舰版”）
- **源码位置**：[`backend/agent/tools.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/agent/tools.py#L35-L85)、[`backend/agent/slot_extractor.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/agent/slot_extractor.py#L106-L111)、[`data/mock_products.json`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/data/mock_products.json#L67-L69)
- **复现链路**：
  1. `ALIAS_MAP` 中键名为 `"暗影精灵16 slim"`（无空格）。第 6 轮买家输入 `"【暗影精灵 16 Slim】"`（带空格），`slot_extractor.py` 第 108 行 `if alias in norm.lower()` 匹配失败，漏提了 `HP-OMEN-16-SLIM`，仅提取了 `HP-ZHAN-99-G5`。
  2. 此时买家画像 `candidate_spus` 中保留着第 1 轮的 `HP-OMEN-10-PRO` 和刚提取的 `HP-ZHAN-99-G5`，误导大模型以为“暗影精灵 16 Slim 在系统里对应的是暗影精灵 10 旗舰版”。
  3. 同时，`data/mock_products.json` 中 `HP-ZHAN-66-G5` 的标题写成了 `"HP 战 66 六代"`（G5 为五代，G6 才是六代），造成用户问“战66五代（HP-ZHAN-66-G5）”时系统回答“战 66 六代”。

### 根因 4：跨机型咨询与全局推荐时，System Prompt 仍强塞前端默认 SPU 锚定事实
- **源码位置**：[`backend/api/v1/chat.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/api/v1/chat.py#L80-L98)
- **复现链路**：
  - 无论买家当前问题是在问其他指定机型（如第 3 轮只问“星 Book Pro 14”），还是在做全局预算筛选（第 4、5 轮），抑或是对比另外两款机型（第 6 轮对比暗影 16 Slim 和战 99），`chat.py` 始终将前端默认选中的 `HP-VICTUS-16` 作为 `【咨询商品规格事实】` 注入 System Prompt，导致模型在回答无关机型时频繁被光影精灵 16 干扰。

### 根因 5：远程模型连接超时阈值过大（16 秒挂死）且本地兜底缺失常识纠偏
- **源码位置**：[`backend/core/llm_client.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/core/llm_client.py#L20-L46)、[`backend/agent/runner.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/agent/runner.py#L165-L298)
- **复现链路**：
  1. `LLMAdapter` 默认 `timeout = 30.0`，未设置独立的 TCP 连接超时（`connect` timeout）和熔断器，网络不可达时底层重试挂起 **16.3s ~ 16.5s** 才抛异常切入本地兜底。
  2. 本地兜底逻辑（`llm_client.py` 第 106-157 行）没有针对“电池/续航”及反常识提问（如“续航 80 小时”）的分支，也没有利用 `runner.py` 刚刚调用的 `get_product_detail` 工具返回结果，直接落入第 156 行万能套话模板，答非所问。
  3. 第 2 轮买家问“战66五代和光影精灵16，能自己加装第二根固态硬盘和升级双通道内存吗？”，本地兜底仅机械罗列四条对比模板，未正面给出“两款均配备 2 个内存槽和 2 个 M.2 固态槽，均支持加装第二根固态与升级双通道内存”的明确结论。

---

## 二、 工业级优化执行方案（逐文件改动清单）

### 优化模块 1：重构输出端护栏 `OutputGuardrail`，实现上下文感知与零误杀
**改动文件**：[`backend/guardrails/output_guard.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/guardrails/output_guard.py)、[`backend/api/v1/chat.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/api/v1/chat.py)

1. **多机型与跨机型场景自动解耦**：
   - 在 `OutputGuardrail` 中增加实体识别：扫描当前子句或整轮上下文提及的商品名称/别名。
   - **单品精准绑定**：
     - 若子句明确提及了某款具体机型（如“星 Book Pro 14”、“战 66”），则自动切换使用**该机型对应的 `ProductItem`** 进行数值校验；
     - 若本轮触发了多机型工具（`compare_products`、`filter_products`）或买家问题指向其他机型，**严禁将前端默认 `req.spu_code` 的参数强行套用到其他机型上**。
2. **差值与快充语义豁免（防止把差价、差重、PD快充当成硬件规格篡改）**：
   - **重量校验豁免**：当 `XXkg` 前后紧邻比较/差值词（如 `轻`、`重了`、`差`、`相差`、`比.*轻`、`比.*重`、`减轻`）时，豁免机身重量替换；
   - **功耗校验豁免**：当 `XXW` 前后紧邻快充/电源词（如 `PD`、`快充`、`充电`、`适配器`）时，豁免显卡 TGP 功耗替换；
   - **价格校验豁免**：当金额前后紧邻差值/预算词（如 `差价`、`相差`、`便宜`、`贵`、`超出`、`预算`、`多出`、`省下`）时，豁免官方售价替换；
   - **M.2 插槽完整短语替换**：修复单/双 M.2 替换正则，匹配完整短语 `r"单\s*M\.2\s*(?:固态)?(?:插槽)?(?:[（(][^）)]*[）)])?"`，杜绝产生 `双 M.2 插槽（支持加装第二根固态） 插槽（仅支持替换升级）` 的拼接语病。
3. **修复流式分片截断逻辑（杜绝腰斩数字产生 `2240Hz`）**：
   - 在 `chat.py` 和 `output_guard.py` 中，移除机械的 `buffer[:40]` 强行截断；
   - 改用安全边界切分：优先按句末标点与换行符 `([，。！？；\n\r])` 切分；若单行超长（如 > 120 字符且不含换行），仅在空白符或非数字/非字母边界处切分，**绝对禁止在数字、英文单词或 Markdown 表格行中途切断**。

---

### 优化模块 2：修复型号归一化解析、槽位提取与商品库元数据一致性
**改动文件**：[`backend/agent/tools.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/agent/tools.py)、[`backend/agent/slot_extractor.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/agent/slot_extractor.py)、[`backend/api/v1/chat.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/api/v1/chat.py)、[`data/mock_products.json`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/data/mock_products.json)

1. **去空格归一化匹配（Space-Insensitive Normalization）**：
   - 在 `tools.py` 的 `resolve_spu()` 和 `slot_extractor.py` 中，先将输入文本与别名做去空格/去横杠归一化（`re.sub(r"[\s\-_]+", "", text.lower())`），确保 `"暗影精灵 16 Slim"`、`"暗影精灵16Slim"`、`"星 Book Pro 14"`、`"战 66 五代"` 100% 精准命中对应 SPU。
2. **修正商品代际名称与别名映射**：
   - 在 `ALIAS_MAP` 中补充 `"战66五代"`、`"战66 5代"`、`"战99移动工作站"` 等常见问法映射，并统一 `HP-ZHAN-66-G5` 标题与别名的一致性。
3. **智能控制 `anchor_fact` 注入时机**：
   - 在 `chat.py` 中先识别买家当前 `query` 中显式提及的机型：
     - 若买家问题明确指向了其他机型（如在 `HP-VICTUS-16` 页面问 `星 Book Pro 14`），自动将 `anchor_fact` 切换为买家实际询问的机型；
     - 若买家在进行多机型对比或全局预算筛选（未指定单一主咨询机型），不强行注入无关的默认单品 `anchor_fact`，避免干扰大模型。

---

### 优化模块 3：LLM 快速超时熔断 + 高质量本地兜底（解决 16 秒挂死与答非所问）
**改动文件**：[`backend/core/llm_client.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/core/llm_client.py)、[`backend/agent/runner.py`](file:///c:/Users/吕海泉/Desktop/EvoRetail-Agent（面向 3C 电商的自进化售前咨询客服）/backend/agent/runner.py)

1. **细粒度超时与快速熔断（Fail-Fast Circuit Breaker）**：
   - 在 `LLMAdapter.get_client()` 中将 `httpx.AsyncClient` 的超时细化为：
     `httpx.Timeout(connect=2.5, read=8.0, write=5.0, pool=3.0)`，并将 `AsyncOpenAI(max_retries=0)` 默认重试次数设为 `0`（避免 SDK 内部静默指数退避重试导致挂死 16 秒）。
   - 增加轻量级内存熔断器：若连续 2 次发生连接超时/网络异常，开启 30 秒快速熔断窗口，窗口期内直接走本地确定性路由（耗时 < 50ms），30 秒后自动半开探活。
2. **升级本地 Fallback 兜底回答质量**：
   - **常识纠偏与续航解答**：在 `llm_client.py` 本地生成器中增加“电池/续航”与反常识夸张数值（如“80小时续航”）识别分支，明确告知买家：“高性能游戏本标配大容量锂电池，日常轻度办公续航约 4~6 小时（高负载游戏需连接电源适配器才能激活满血功耗），目前笔记本电脑不存在 80 小时续航的规格”，并基于目标机型真实参数予以专业回复；
   - **对比问答正面回应具体问题**：在 `runner.py` 的本地 `compare_products` 模板中，若买家询问“加装固态 / 升级内存”，在对比表格之外显式给出针对性结论（如明确回答哪款支持双内存槽/双 M.2 槽无损加装，哪款为板载内存/单槽）。

---

## 三、 验收标准与自动化测试计划

优化完成后，将通过以下新增与现有的自动化测试进行严格实证验收（全部通过才算完成）：

1. **复刻 6 轮实测对话的端到端回归测试（新增 `tests/test_real_world_dialogues.py`）**：
   - **用例 1（反常识续航提问 + 兜底质量）**：询问 `HP-OMEN-10-PRO` 续航能否达到 80 小时，验证响应耗时可控，且明确纠偏“不能达到 80 小时”，绝不答非所问。
   - **用例 2（跨机型加装对比 + 差价差重算术）**：在 `spu_code="HP-VICTUS-16"` 下对比 `HP-ZHAN-66-G5` 与光影精灵 16，验证战 66 价格保持 `¥4299`、重量保持 `1.7kg`、功耗保持 `45W`、差价 `2700 元`、差重 `0.6kg`，绝不被篡改为 `¥6999` 和 `2.3kg`。
   - **用例 3（跨机型咨询星 Book Pro 14）**：在 `spu_code="HP-VICTUS-16"` 下询问 `星 Book Pro 14` 是否为 140W 满血独显，验证回复中星 Book Pro 14 价格为 `¥5499`、重量为 `1.4kg`、功耗为 `45W`、扩展性为“单 M.2 插槽”，无拼接病句。
   - **用例 4 & 5（预算筛选 7000~8000 / 5000 以内）**：验证各候选机型价格真实独立（战 66 七代 `¥4599`、战 66 六代 `¥4299`、星 Book Pro 14 `¥5499`、暗影 10 Pro `¥12999`），绝不出现“预算 5000 推荐 ¥6999”的倒挂现象。
   - **用例 6（暗影精灵 16 Slim 与战 99 对比 + Markdown 表格流式分片）**：验证准确解析出 `HP-OMEN-16-SLIM`（`¥8999`、`2.1kg`、`RTX 4070`）与 `HP-ZHAN-99-G5`（`¥7499`、`2.2kg`、`60Hz`），且流式切分表格行时绝不出现 `2240Hz`。
2. **全量基准测试回归**：
   - 运行 `python -m pytest tests -v`，确保原有 47 项单元测试与新增回归测试 **100% 通过**。

