---
name: anomaly-atlas
description: 把一份 CSV 时间序列变成"可复算的异常档案"——单文件 HTML 标注图 + Phase 卡 + 数字白名单门禁。当用户要求"时序异常检测/异常标注可视化/异常复盘报告/给这份传感器数据找出异常段并出一份能复核的报告/复算 sha256 徽章"，或提到 anomaly-atlas、Episode、run-spec、facts.json 白名单时使用。输入是一份本地 CSV（时间戳列 + 数值列，可选 series_id），输出是单个 HTML 文件（断网可开、零外部请求）与一份通过白名单校验的叙事报告。
---

# anomaly-atlas · 时序异常标注可视化

**一句话**：数据不出本机；异常集由 `run-spec` 唯一决定；读者用自己浏览器里的那份手写 JS 镜像重算出同一个 `sha256`，一致才显示 **VERIFIED**。模型只负责"把结论讲清楚"，不产生任何一个异常点、参数或指纹。

## 何时用这个 skill

- 用户给了一份**本地** CSV 时序数据（时间戳 + 数值，可能多指标），想找出异常区间并要一份能复核的档案。
- 用户要"异常复盘报告"，并且在意**可信**：每个数字都能追到一条内核事实，报告里的数字不能编。
- 用户想验证一份已有 `examples/atlas.html` 是否被篡改过（复算徽章）。
- 不适合：实时流式监控、告警推送、深度学习检测器、通用图表美化（本 skill 只服务异常语义）。

## 四步工作流

以下命令用**源码直跑**口径（`PYTHONPATH=src`）；`pip install -e .` 之后用 `anomaly-atlas` 子命令等价（省掉 `PYTHONPATH` 与 `-m` 前缀）。需要 Python >= 3.8，零第三方运行时依赖；复算门禁需要 Node（缺失会明确 exit 4）。

```bash
# 0. 环境
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli --version

# 1. 剖面：先看数据长什么样（节奏、缺口、缺失段、零值段、重复戳、质量卡）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli profile <你的.csv> -o profile.json

# 2. 检测：出 run.json（生效参数）/ anomalies.json（Episode）/ anomaly_set.sha256（指纹）
#    以及 facts.json——报告数字的唯一权威来源
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli detect <你的.csv> --out-dir out

# 3. 渲染：单文件标注图（零外链、断网可开、可黑白打印）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli render <你的.csv> -o atlas.html

# 4.（可选但推荐）把模型写的叙事交给白名单门禁，通过后写进页面的报告区
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli check-report --facts out/facts.json --text report.md
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli render <你的.csv> -o atlas.html --narrative report.md

# 5. 复核（人读 + 机器读两面都要过）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli verify atlas.html          # -> VERIFIED, exit 0
PYTHONPATH=src py -X utf8 tools/mirror_parity.py --html atlas.html        # 同一判定的工具入口
```

读完 `atlas.html` 后**指读徽章**：页面顶部的徽章显示绿色 **VERIFIED**（构建指纹 == 复算指纹，两串同一 sha256），或红色 **MISMATCH** 并给出首个差异点（series / detector / 第几个点 / 期望 / 实算 / 源行号）。没有 Node 也能开这个页面——复算发生在浏览器里。

## 模型分工声明（题面硬约束）

| 只能由代码产出 | 由模型负责（表达层） |
| --- | --- |
| 异常点、Episode 边界、`episode_id`、严重度排序 | 数据语义判断（这批指标在业务上意味着什么） |
| 检测器参数生效值、阈值线、`max_gap_ms` 合并结果 | 阈值取舍的**理由**（为什么 k=3.5 合理） |
| 所有指纹（异常集 / 真值 / 浏览器复算）| Episode 命名与可能原因 |
| 图上每个坐标、分箱、颜色档位 | 叙事文本（背景、影响、建议的下一步） |
| `facts.json` 里的每个数字 | —— |

模型**不得**：手改异常点、新增未检测到的点、在叙事里写未命中 `facts.json` 的数字、引用不存在的 `episode_id` 或档案外的行号。这不是口头约定：

- `render --narrative` 在**构造期**跑白名单门禁；未命中即 **exit 1**、逐条列出、**不生成产物**。
- 独立入口 `check-report` 给出同样的判定（exit 1），不产生任何副作用。

## 输入 schema（CSV 列角色）

| 列 | 必需 | 说明 |
| --- | --- | --- |
| 时间戳列 | 是 | 自动识别常见同义列名，或显式声明。接受 `YYYY-MM-DD[T ]HH:MM[:SS[.f{1,9}]][Z \| +HH:MM \| +HHMM \| +HH]`；无偏移按声明时区解释（默认 UTC） |
| 数值列 | 是 | 空串 = **缺失**（记 `None`，不补 0、不插值；会喂给缺失段规则） |
| `series_id` 列 | 否 | 多指标长表；缺省视为单一 series |

行号一律是**物理 CSV 行号（1 起，含表头偏移）**。错误**一次报全**、每条带源行号或列名：

| 错误码 | 触发 |
| --- | --- |
| `E_EMPTY_FILE` | 空文件或只有表头 |
| `E_MISSING_COLUMN` | 缺时间戳列或数值列 |
| `E_DUPLICATE_COLUMN` | 重复列名或列名歧义 |
| `E_TS_UNPARSEABLE` | 时间戳不可解析（带行号与原文） |
| `E_VALUE_UNPARSEABLE` | 数值不可解析（带行号与原文；空值不算错） |
| `E_DUPLICATE_TIMESTAMP` | 同一 series 内重复时间戳超过阈值 |
| `E_NON_MONOTONIC` | 时间戳非单调（超过乱序容差） |

## 退出码表

| 码 | 含义 | 典型触发 |
| --- | --- | --- |
| **0** | 成功 | 命令正常完成（`verify` 为 VERIFIED） |
| **1** | 门禁或自检发现缺陷（产品是错的） | `check-report` / `render --narrative` 有未命中数字；复算 MISMATCH；`selftest` 某项或某项探针失败 |
| **2** | 用法与输入错误 | 缺文件、CSV 契约失败、未知子命令、未知 spec 键、产物不合嵌入契约、篡改下标越界、叙事里出现 `$` |
| **4** | 环境前提不满足 | `verify` / `mirror_parity` 找不到 Node（**不回退、不静默跳过**） |

**没有退出码 3**：骨架期的"阶段未就绪"标记已随 M5 全线退役（`STAGE_NOT_READY` 为空、`EXIT_NOT_READY` 常量已删除，测试正向断言"没有任何命令答 3"）。

## 写叙事时要遵守的两条硬规则

1. **每个数字都要能命中 `facts.json` 的一条 `fact_id`**。命中是"值相等"，不是"看起来像"：
   - 千分位、百分号、小数、科学计数法都会归一化后比较；`42.34%` 也可以命中一条比值事实 `0.423400`。
   - 中文数字**必须带量词**才算数（`三处`、`十五条`；`统一`、`一般`、`十分` 不是测量）。
   - 时间戳可以照页面上的 ISO 写（`2024-03-02T07:00:00.000Z`），门禁会换算成 epoch 毫秒去比对档案里的 `start_ms`/`end_ms`。
   - 行号写 `row N` / `第 N 行`（必须是档案里出现过的行号）；**解析层面的物理行**要明确标成 `CSV 行 N` / `文件行 N`，那类引用不受白名单管辖。
2. **每个 `episode_id` 都要在档案里存在**（正则 `[A-Za-z0-9_]+-E\d{3}`）。写不出来就别写——未命中的引用会被逐条列出，产物不会生成。

> 诚实边界：白名单是**值级**的——一个恰好等于某条事实的编造数字（例如把"653 个异常点"写成"178 个异常点"，而 178 也是 Episode 总数）能过。门禁保证的是"这个数字在档案里有出处"，不是"这个数字被用在了正确的地方"。

## 复算口径（如何自己验证那个徽章）

- **规范 JSON**：键排序、`ensure_ascii=False`、2 空格缩进、LF、结尾换行；**只含整数与字符串**（浮点在哈希边界做 6 位定点化，十进制展示串由整数构造）；这是 `sha256` 的唯一输入形态（`data/README.md` §4.3）。
- **异常集指纹** = `sha256(规范 JSON({run 生效参数, episodes, summary}))`，落在 `out/anomaly_set.sha256`；改任一参数必改指纹（有逐项测试）。
- **浏览器复算** = 产物内联的**手写 JS 镜像**（不是 Python 的转译副本）对同一份内联数据重跑同一套检测算法 → 同一份规范 JSON → 同一 `sha256`；`verify` 在 Node 下做同样的事，与构建值**逐字节**比较，再逐点比较并定位首个差异点。
- **数值可镜像纪律**：进入哈希路径的算术只用 `+ - * / floor ceil abs min max` 与比较；幂次展开为连乘；**禁用一切超越函数与库归约函数**。这是复算不会随机 MISMATCH 的前提（否则两个语言的 libm 差 1 ulp 就让徽章变红）。
- 自己动手验一遍：

```bash
# 机器读的一面：Node 下逐字节对账；篡改一个内联样本必须变红并指名该 series
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli verify atlas.html
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli verify atlas.html --tamper-index 3    # -> MISMATCH + 定位, exit 1

# 人读的一面：双击 atlas.html（断网也能开），看徽章是 VERIFIED 还是 MISMATCH
# 页面零外部请求：DevTools Network 应只有这一次文档加载
```

## 交付前自检

```bash
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli selftest    # 6 项检查 + 6 条可证伪探针，全绿 -> exit 0
```

`selftest` 覆盖：冻结产物台账、真值全段对账（39/39 段 + 6 条合并探针）、冻结指纹（`6020a3d3…`）、改参数必改指纹、剖面双跑一致、**数字白名单（自己的引用能过，编造的数字/Episode/行号必被拒且逐条列出）**。每条检查都配一条探针；探针不变红即按缺陷上报（exit 1），所以"全绿"不是"这个套件没在干活"。

## 相关文件

| 路径 | 内容 |
| --- | --- |
| `README.md` | 定位、使用方式、确定性声明、已知环境问题 |
| `data/README.md` | 数值口径的**唯一权威定义处**（检测器参数 / 合并排序 / 规范 JSON 与哈希 / 错误码 / 数字白名单） |
| `examples/atlas.html` | 合成数据生成的成品（断网可开；复用同一份 `verify` 命令） |
| `plan/` | 题目文档、架构、模块详设、数据计划、里程碑、交付对标与决策记录、逐棒 HANDOFF |
| `plan/自评表.md` | 评分四栏自评 + 每项挂证据（测试名 / 命令 / 实测输出） |
