# data/ 数据说明

本目录承载合成时序数据、程序化植入的真值与基准哈希。**没有任何外部数据依赖**：用户自备 CSV 即可使用本 Skill。

## 1. 依据查证记录（基准日 2026-10-17，GitHub `gh api`）

以下检索为出题阶段快照，属**软论据**（⬜），星数会随时间变化；判定结论依赖的是形态事实（✅）。

| 检索式 | 命中数 | 代表仓库与星数 | 判定 |
| --- | --- | --- | --- |
| `anomaly detection visualization time series` | 142 | msda 129★、microsoft/A-TALE-OF-THREE-CITIES 90★、Anomaly-Detection-Platform 9★ | 库/论文代码/平台，非 agent skill |
| `anomaly detection skill` | 116 | cloud-finops-skills 63★、Anomaly-Detection 26★ | 与"时序异常标注交付"无关 |
| `time series anomaly agent skill` | 2 | TimeSeries_Analysis_Skills 8★（仅 README，无 SKILL.md 实现）、wikipulse 0★ | 形态空白最强证据 |
| `anomaly detection visualization skill agent` | 0 | — | 无命中 |
| `timeseries anomaly visualization tool` | 0 | — | 无命中 |
| `anomaly detection html report` | 67 | 全部 ≤3★，均为应用/仪表盘 | 非 skill，交付形态不同 |
| `time series anomaly detection dashboard` | 166 | Theseus 24★（2023 停更） | Dashboard 需部署，非单文件档案 |
| `time series analysis skill claude` | 4 | 全部 0★ | 无成熟竞品 |

库层参照（✅ 事实区分）：pyod 10043★、darts 9551★、PyPOTS 2077★ 是引擎；Theseus 24★ 是论文 Dashboard；thirdeye 97★ 是平台。最接近的 skill 是 genpark matrix-profile discord skill 7★，只输出 Top-N 列表，无标注图、无 Episode、无复算。

**判定：库层极卷、交付层极空，空白成立。**

## 2. 数据源可获取性

| 项 | 结论 |
| --- | --- |
| 外部数据依赖 | **无**。用户自备 CSV（时间戳列 + 数值列，可选 `series_id`） |
| 演示数据 | 程序化合成的虚构场景时序，随仓库入库 |
| 网络要求 | 无。构建与查看全程离线；HTML 零外部请求 |
| 隐私 | 数据纯本地处理、不上传；用户须自行确认数据可被处理 |

## 3. 合成数据纪律

1. **程序化生成**：合成时序由生成器脚本产出，不使用手抄数字。序列包含：
   - 已知周期性（周期长度由生成参数决定，并写入 manifest）；
   - 已知趋势与噪声参数；
   - **植入的异常段**：尖峰、电平漂移、方差突变、连续缺失/零值段；
   - **已知缺口**：显式断档，用于验证缺口纹理。
2. **真值即生成参数**：异常区间集合（起止、类型、植入幅度）在生成时同时导出为真值文件；真值是生成器的输出，不是事后人工标注。
3. **真值哈希**：对真值异常集按 §4 的规范 JSON 规则计算 `sha256` 并入库；检测内核对该数据的输出必须与真值集合及哈希一致。
4. **可重跑**：固定随机种子与生成参数后，重复运行生成器必须产出 byte-identical 数据与真值；生成器参数与种子写入 manifest。
5. **虚构标注**：合成场景名称明确标注"（虚构）"，不影射真实企业、真实业务数据或真实事件。
6. **冻结**：入库后的数据与真值视为冻结资产；如需重新生成，必须同时更新 manifest、真值与哈希，并在提交说明中写明原因。

## 4. 数值口径纪律（唯一权威定义处）

题面、模块文档、报告均**引用**本节，不复写。任何口径变更必须先改本节，再改代码与测试。

### 4.1 检测器参数

| 检测器 | 参数 | 含义 |
| --- | --- | --- |
| `rolling_mad_z` | `window`, `k`, `min_valid` | 滚动中位数与 MAD 稳健 z（尺度系数 `1.4826`）；`|z| > k` 判异常；窗口内有效点 < `min_valid` 时该点**不高判** |
| `rolling_iqr` | `window`, `iqr_mult`, `min_valid` | 滚动四分位距（线性插值分位）；越出 `[Q1 − m·IQR, Q3 + m·IQR]` 判异常 |
| `stl_resid_z` | `period_points`, `inner`, `outer`, `window`, `k`, `min_valid` | 经典 STL（LOESS，bisquare 权重 `(1−w²)²`）残差 z；`period_points` 由自相关估计或用户显式声明 |
| `rules` | `static_threshold`, `pct_jump`, `missing_run`, `cusum_k`, `cusum_h` | 静态阈值、百分比突变、连续缺失/零值段、CUSUM 两窗均值漂移 |

- **参数最终取值一律写入 `run.json`（run-spec），成为复算的唯一依据**；模型可以给出取舍理由，但不得绕过 run-spec 直接改判定。
- `run.json` 记录的是**解析后的生效值**：`period_points` 记 ACF 估出的结果（而非"估计器"本身），`max_gap_ms`、`quant_decimals`、算法/规范版本号一并记录。复算侧消费生效值，不重跑估计——避免"估计器实现差异"污染指纹。
- 默认值（未声明时）：见 `plan/06` 待定决策表 P4；任何默认值都必须在 `run.json` 里显式出现，**引擎里不留隐形默认**。
- 缺失/零值/缺口不是"可跳过的东西"：规则型检测器按连续性判，滚动型检测器按 `min_valid` 降级，剖面按区间登记。

### 4.2 Episode 合并与排序

- 相邻异常点（按时间序）间隔 `≤ max_gap_ms`（**整数毫秒**）即合并为同一 Episode；
- Episode 字段：`episode_id`、`series_id`、`detector`、`start`、`end`、`duration_ms`、`peak_score_q`、`n_points`、`start_row`、`end_row`、`threshold_ref`；
- 严重度排序键（确定性、逐级比较，**全部为整数或字符串**）：`peak_score_q` 降序 → `duration_ms` 降序 → `start_row` 升序 → `detector` 字典序；
- `episode_id = "<series_id>-E<NNN>"`，NNN 为该 series 内排序后的序号（1 起）；同一 run-spec 必得同一组 id。

**为何用时间域而不点数**：点数间隔会跨数据缺口把两段本不相邻的异常合并（语义错误）；时间域与采样节奏解耦，且不跨缺口。**为何用定点整数排序**：原始浮点在近并列处可能给出跨语言不同的次序，进而 id 与指纹全变（详见 §4.3）。

### 4.3 规范 JSON 与哈希

本规范 JSON 是 `sha256` 的**唯一输入形态**，Python 构建侧与浏览器 JS 镜像必须字节一致地产出它。

- **键排序**：对象键按 Unicode 码点升序；
- **只允许的值类型**：字符串、整数、布尔、`null` 及其数组/对象。**不允许浮点字面量**——任何浮点在做哈希前必须定点化为整数；
- **浮点定点化**：`q = 半偶舍入(x × 10^quant_decimals)`（`quant_decimals` 默认 6，写入 `run.json`）。
  半偶舍入用整数算术表达：令 `s = x × 10^d`、`f = s − floor(s)`，则 `q = floor(s) + (f > 0.5 ? 1 : (f < 0.5 ? 0 : floor(s) 为奇数 ? 1 : 0))`；
  **禁用语言自带的浮点格式化**（`f"{x:.6f}"` / `toFixed` 的边界行为不可对齐），也**禁用科学计数法**；
- **十进制展示串**由整数构造（`sign + q // 10^d + "." + 补零(q % 10^d, d)`），两端用同一整数算法；
- **数值可镜像纪律**：进入哈希路径的算术只允许 IEEE-754 基本运算（`+ − × ÷`）、`floor/ceil/abs/min/max` 与比较；**禁止一切超越函数**（`exp/log/pow/sin/cos/sqrt`）与库归约函数（`np.mean/sum`、`statistics.mean`），幂次展开为连乘。理由见 `plan/02` §3.2；
- **编码**：UTF-8、无 BOM、LF、无多余空白（JSON 序列化参数：`sort_keys=True, ensure_ascii=False, indent=2` + 结尾换行）；
- **哈希输入**：只取规范 JSON 的字节序列，`sha256` 以十六进制小写输出；
- **适用范围**：异常集指纹、真值指纹、浏览器复算指纹**必须使用同一规则与同一实现**。

**时间口径（哈希与展示同源）**：一切时间戳规范化为 **UTC 整数 epoch 毫秒**；落盘 ISO 串为定点形式 `YYYY-MM-DDTHH:MM:SS.mmmZ`，由整数反算得出（不经过本地时区库）。`start_row`/`end_row` 为 CSV 源行号（1 起，含表头偏移的原始行号）。

### 4.4 错误码

输入错误使用稳定错误码，每个错误必须携带**源行号或列名**，错误码表在实现中单点定义（`src/anomaly_atlas/csvio.py` 的 `ERROR_CODES`）；错误一次性收集后统一报出（非首错即停），退出码归 **2**（用法与输入错误）。

| 错误码 | 触发 |
| --- | --- |
| `E_EMPTY_FILE` | 空文件或只有表头 |
| `E_MISSING_COLUMN` | 缺时间戳列或数值列（同名同义词表匹配不到且无显式指定） |
| `E_DUPLICATE_COLUMN` | 出现重复列名，或列名歧义无法唯一判定 |
| `E_TS_UNPARSEABLE` | 时间戳不可解析（带源行号与原始文本） |
| `E_VALUE_UNPARSEABLE` | 数值不可解析（带源行号与原始文本；**空值不算错**，记为缺失） |
| `E_DUPLICATE_TIMESTAMP` | 同一 series 内重复时间戳超过阈值（阈值进 run-spec） |
| `E_NON_MONOTONIC` | 时间戳非单调（超过允许的乱序容差） |

### 4.5 数字白名单

`facts.json` 是报告数字的唯一权威来源：内核导出的每个数字（异常数、最大得分、持续时长、峰值、行号、缺口计数、分箱覆盖度等）都带唯一 `fact_id`。报告中的数字必须命中某条 `fact_id`，未命中即失败（**exit 1**）并列出未命中数字及其上下文，报告不生成。

---

## 5. 目录约定

| 路径 | 内容 | 落地里程碑 |
| --- | --- | --- |
| `data/synthetic/series.csv` | 合成时序（长表 `timestamp,series_id,value`）+ 生成 manifest（参数、种子、周期、注入的异常段、逐文件 sha256 台账） | M1 |
| `data/truth/truth.json` | 真值异常区间集合（只存输入与期望，禁 `observed`） | M1 |
| `data/truth/hash.txt` | 真值异常集按 §4.3 规范 JSON 计算的 `sha256` | M1 |
| `data/samples/minimal.csv` | 最小示例 CSV（≤20 行，可人眼核对），供快速试跑 | M1 |

**冻结纪律**：M1 落盘后视为只读资产；改动必须走生成器 + `--check` 位级一致守门（冻结产物形态 + 重生成逐字节比对两层），并在提交说明中写明原因。一切快照 LF + UTF-8 无 BOM，故 `.gitattributes` 的 `* text=auto eol=lf` 不改变克隆字节、台账 sha256 在任意克隆中成立。
