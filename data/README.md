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
| `rolling_mad_z` | `window`, `k` | 滚动中位数与 MAD 稳健 z；`|z| > k` 判异常 |
| `rolling_iqr` | `window`, `iqr_mult` | 滚动四分位距；越出 `[Q1 − m·IQR, Q3 + m·IQR]` 判异常 |
| `stl_resid_z` | `period`, `window`, `k` | STL 残差 z；`period` 由自相关估计或用户显式声明 |
| `rules` | `static_threshold`, `pct_jump`, `missing_run`, `cusum_k`, `cusum_h` | 静态阈值、百分比突变、连续缺失/零值段、CUSUM 两窗均值漂移 |

参数最终取值一律写入 `run.json`（run-spec），成为复算依据；模型可以给出取舍理由，但不得绕过 run-spec 直接改判定。

### 4.2 Episode 合并与排序

- 相邻异常点（按时间序）间隔 `≤ max_gap` 即合并为同一 Episode；
- Episode 字段：`episode_id`、`start`、`end`、`duration`、`peak_score`、`n_points`、`detector`、`source_rows`；
- 严重度排序键（确定性、逐级比较）：`peak_score` 降序 → `duration` 降序 → `start` 升序 → `detector` 字典序；
- `episode_id` 由排序后的序号生成，同一 run-spec 必得同一组 id。

### 4.3 规范 JSON 与哈希

- **键排序**：对象键按 Unicode 码点升序；
- **浮点定点**：所有浮点统一格式化为固定小数位（位数在实现中单点定义并写入 run-spec 版本），禁止科学计数法；
- **编码**：UTF-8、无 BOM、无多余空白；
- **哈希输入**：只取规范 JSON 的字节序列，`sha256` 以十六进制小写输出；
- **适用范围**：异常集指纹、真值指纹、浏览器复算指纹必须使用同一规则。

### 4.4 错误码

输入错误使用稳定错误码（缺列、时间不可解析、数值不可解析、空文件、重复时间戳超限等），每个错误必须携带源行号或列名，错误码表在实现中单点定义。

### 4.5 数字白名单

`facts.json` 是报告数字的唯一权威来源：内核导出的每个数字（异常数、最大得分、持续时长、峰值、行号、缺口计数等）都带唯一 `fact_id`。报告中的数字必须命中某条 `fact_id`，未命中即失败。

---

## 5. 目录约定（后续里程碑填充）

| 路径 | 内容 |
| --- | --- |
| `data/synthetic/` | 合成时序 CSV + 生成 manifest（参数、种子、周期、注入的异常段） |
| `data/truth/` | 真值异常区间集合 + 真值 `sha256` |
| `data/samples/` | 可选的最小示例 CSV（用于快速试跑） |
