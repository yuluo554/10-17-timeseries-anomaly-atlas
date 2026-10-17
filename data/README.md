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
3. **真值必须可被检出（可检出性下限）**：生成器在写盘前除了断言"每类 ≥2 段、有窗口边界段、探针两侧齐"之外，还断言**幅度下限**——每类加性异常（尖峰/电平漂移）的幅度 ≥ 8 × 该指标的噪声幅度，且日周期摆幅 ≥ 3 × 噪声幅度。理由来自 M2 的实测：M1 冻结数据里 humidity 的植入尖峰只有 1800–2200 milli，而它的噪声幅度是 600 milli，于是**任何**可用阈值下的稳健 z 都到不了 3.5（实测最大 z = 2.77），日周期（910 milli 摆幅）也只有噪声的 1.5 倍、无法被周期估计器找到——一份"自己声称的异常根本检不出来"的基准会让对账门禁要么说谎、要么变成一个没人敢动的豁免清单。修复方式是把该指标的噪声幅度降到 200 milli（一处数值，不动植入幅度与行号），**真值指纹 `ad3822a1…` 因此保持不变**；见 `plan/06` D19。
4. **真值哈希**：对真值异常集按 §4 的规范 JSON 规则计算 `sha256` 并入库；检测内核对该数据的输出必须与真值集合及哈希一致（"一致"的确切含义见 §4.3 末段：全段对账，不是指纹相等）。
5. **可重跑**：固定随机种子与生成参数后，重复运行生成器必须产出 byte-identical 数据与真值；生成器参数与种子写入 manifest。
6. **虚构标注**：合成场景名称明确标注"（虚构）"，不影射真实企业、真实业务数据或真实事件。
7. **冻结**：入库后的数据与真值视为冻结资产；如需重新生成，必须同时更新 manifest、真值与哈希，并在提交说明中写明原因。

## 4. 数值口径纪律（唯一权威定义处）

题面、模块文档、报告均**引用**本节，不复写。任何口径变更必须先改本节，再改代码与测试。

### 4.1 检测器参数与判定口径

| 检测器 | 参数 | 含义 |
| --- | --- | --- |
| `rolling_mad_z` | `window`, `k`, `min_valid` | 滚动中位数与 MAD 稳健 z（尺度系数 `1.4826`）；`\|z\| > k` 判异常；窗口内有效点 < `min_valid` 时该点**不高判** |
| `rolling_iqr` | `window`, `iqr_mult`, `min_valid` | 滚动四分位距（线性插值分位）；越出 `[Q1 − m·IQR, Q3 + m·IQR]` 判异常 |
| `stl_resid_z` | `inner`, `outer`, `window`, `k`, `min_valid` | 经典 STL（LOESS 趋势 + 相位季节项、bisquare 权重 `(1−w²)²`）残差 z；残差用**与 `rolling_mad_z` 同一实现**的滚动中位数+MAD 打分（口径不复制） |
| `rules` | `static_threshold`, `pct_jump`, `missing_run`, `cusum_k`, `cusum_h` | 静态阈值、百分比突变、连续缺失/零值段、CUSUM 跳变 |
| 运行级 | `max_gap_ms`, `period_points`, `period_reject_window`, `period_reject_sigma`, `quant_decimals` | Episode 合并阈值（§4.2）、周期生效值、周期估计器的剔除窗口/倍数、定点小数位（§4.3） |

**共同口径（四类检测器都遵守）**

- **窗口**：`[i − window + 1, i]`，**含被评点**、尾部对齐；窗内有效点 < `min_valid` 则该点不高判（`min_valid` 默认 6 = `window // 4`）。首尾样本窗口自然变短，不补值也不外推。
- **缺失值永不参评**：`None` 是数据（它是缺失段规则的输入），不是被打分的点；窗口内缺失点只减少有效计数。
- **退化窗口显式定义**（不许靠"除零得 inf 再比较"）：MAD = 0（窗口内超过半数恰好落在中位数上）时回退到**平均绝对偏差**仍可给尺度；IQR = 0 时同样回退。尺度为 0（窗口全部相同）时该点**无法被判**，得分记 0、不判异常。
- **只产出原始得分**：检测器返回 `(点, score)`（`rules` 另带规则名），不合并不排序不命名——那是 `episodes.py` 的唯一职责（§4.2）。

**`stl_resid_z` 分解口径**

- 趋势 = LOESS（一次局部线性、tricube 权重、窗口 `next_odd(1.5 × period_points)`，边界收缩窗口而不外推）。
- 季节 = 各相位（**相位 = 时间栅格下标 mod `period_points`**）的加权均值，再沿相位轴做一次 LOESS 平滑（窗口 `next_odd(period_points/3)`；相位轴三倍复制后取中间一段，保证周期首尾连续）。**相位必须取自时间栅格**：丢点会让后续样本的列表位置整体错一位，按位置折叠会把季节项涂糊。
- 内循环 `inner` 次（切季/切趋势各一次）、外循环 `outer` 次（每次用 bisquare 权重 `(1−u²)²`、`u = |残差| / (6 × 残差中位数)` 重加权）。
- `period_points ≤ 1` = **无季节项**：季节项退化为全序列均值，分解只剩趋势 + 残差。这就是"序列太短、找不到任何 ≥2 的周期"时的生效口径（不静默跳过、也不猜一个周期）。

**`period_points` 生效值的来历**（复算侧只消费生效值，不重跑估计，D13）

1. run-spec 显式声明 → 直接采用（`period_source=declared`）。
2. 未声明 → 逐 series 用**稳妥 ACF** 估计，取各 series 估计值的**中位数**（偶数取偏小者）作为运行级生效值（`period_source=estimated`）：
   - 残差 = 原序列 − 居中滚动中位数（`period_reject_window`，默认 121）；
   - **剔除**（置为缺失，而非替换）残差超过 `period_reject_sigma`（默认 2.5）倍稳健尺度的栅格单元；
   - 再扣最小二乘直线、按 3 倍稳健尺度截尾；
   - 在**时间栅格**上做两两（pairwise）自相关，在 `[max(8, n/16), n/3]` 内取最强局部极大；若某约数仍能解释该相关性的 ≥ 80%，取该约数（基频优先，避免把 2 倍周期当周期）。
   - 为什么不是"直接对原序列做 ACF"：实测在冻结数据上，9 点零值段一项就占了整段方差的 78%，26–41 点的电平漂移又在前 41 个滞后上叠加一片宽肩，峰值会漂到 2…302 的任意处；先剔异常再算 ACF 才回到 288。
3. 两者都没有（序列太短/无周期）→ `period_points = 1`（`period_source=no-cycle-default`），即口径 2 的"无季节项"。

**`rules` 各子规则口径**

- `static_threshold`：`null` = **关闭**；非 null 时按幅度上界判 `|x| > threshold`，得分 = 超出量。
- `pct_jump`：相邻**有效**点 `|x_t / x_{t−1} − 1| > pct_jump`；前一点为 0 时相对变化无定义，**该规则不表态**（零值基线归零值段规则处理），缺失点打断配对。
- `missing_run` / `zero_run`：连续缺失（或连续 `0.00`）长度 ≥ `missing_run` 即整段判异常，**得分 = 段长**（段越长越严重）。
- `cusum`：相邻有效点差分按差分自身的稳健尺度标准化（`u`），双侧累加 `S± = max(0, S± ± u − cusum_k)`，`max(S+, S−) > cusum_h` 报警并**重置两个累加器**（经典 CUSUM 重启策略；不重置会把一次偏移报成一长串）。仅在有效相邻点上推进，缺失点既不推进也不重置。若差分尺度低于 `10^−quant_decimals ×` 序列自身稳健尺度（直线/常数序列：没有短期噪声），该规则**不表态**——否则最后一个二进制位会被标准化成"天文数字般的跳变"。

**参数落盘形态**：`run.json` 里的十进制参数（`k`、`iqr_mult`、`pct_jump`、`cusum_k`、`cusum_h`、`period_reject_sigma`）以 **6 位定点字符串**落盘（由整数构造，见 §4.3），整数参数保持整数、`static_threshold` 未启用时为 `null`。人读的就是被哈希的那一份，不存在第二个表示。

- **参数最终取值一律写入 `run.json`（run-spec），成为复算的唯一依据**；模型可以给出取舍理由，但不得绕过 run-spec 直接改判定。
- `run.json` 记录的是**解析后的生效值**：`period_points` 记估计结果（而非"估计器"本身），`max_gap_ms`、`quant_decimals`、算法/规范版本号一并记录。复算侧消费生效值，不重跑估计——避免"估计器实现差异"污染指纹。
- 默认值（未声明时）：见 `plan/06` 待定决策表 P4；任何默认值都必须在 `run.json` 里显式出现，**引擎里不留隐形默认**。
- 缺失/零值/缺口不是"可跳过的东西"：规则型检测器按连续性判，滚动型检测器按 `min_valid` 降级，剖面按区间登记。

### 4.2 Episode 合并与排序

- 相邻异常点（按时间序）间隔 `≤ max_gap_ms`（**整数毫秒**）即合并为同一 Episode；合并**按 `(series_id, detector)` 分组**进行——不同检测器的证据各自成段，不互相并吞（同一个点被两个检测器都判到，就诚实地呈现两段证据）。
- Episode 字段：`episode_id`、`series_id`、`detector`、`start`、`end`、`duration_ms`、`peak_score_q`、`n_points`、`start_row`、`end_row`、`threshold_ref`；
- `threshold_ref` = 触发该段的那一族检测器的**生效参数块**（与 `run.json` 里的同一份落盘形态，见 §4.1），读者可据此复现阈值；
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

**异常档案的三个指纹（别混用）**

| 指纹 | 覆盖对象 | 落点 |
| --- | --- | --- |
| 异常集指纹 | `anomalies.json` 全文：`run`（**生效参数**：解析后的 `k`/`window`/`min_valid`/`rules` 各项、`max_gap_ms`、`period_points`、`quant_decimals`、算法与规范版本号、源文件 sha256）+ `episodes` + `summary` | `out/anomaly_set.sha256` |
| 真值指纹 | 生成时植入的异常段集合（`scenario`/`seed`/`cadence_ms`/`max_gap_ms`/`window_points`/`segments`） | `data/truth/hash.txt` |
| 浏览器复算指纹 | 前端镜像重跑后产出的同一份规范 JSON（M3） | HTML 内嵌 |

**为什么"生效参数"在指纹里**：只哈希 episode 列表的话，"改任一参数指纹必变"会在"参数改了但判定恰好没动"时失效；而复算侧消费的正是生效参数，所以它属于指纹的一部分。

**真值指纹 ≠ 检测指纹**（§3.3 的"一致"含义）：检测内核的输出与真值**一致**指**全段对账**（`anomaly-atlas selftest` 的 `truth-reconciliation` 检查）——39 段植入异常**逐段**被至少一个 episode 覆盖（不是抽样比例），且 `max_gap_ms` 两侧的合并探针按 `expected_merged` 判定；不指两个指纹相等。二者本来就不该相等：`max_gap_ms` 两侧的探针里"25 分钟"那三对**必须合并成一个 episode**（K7 口径），而真值把它们记作两段植入——这是口径正确，不是不一致。

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
