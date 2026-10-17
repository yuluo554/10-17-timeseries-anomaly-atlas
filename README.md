# anomaly-atlas · 时序异常标注可视化 Skill

**把一条时间序列变成"可复算的异常档案"——每个异常区间都带检测器、参数、得分、源行号，并能在浏览器里当场重算出同一集合（run-spec → sha256 → 浏览器复算 → VERIFIED 徽章）。**

时间序列异常检测在算法层已经非常成熟：有通用异常检测库、时序建模库、部分观测时序学习库（此处仅作事实引用）。它们都是**引擎**——能力齐全，但交付物止步于"函数返回一个标签数组"。真正消耗分析师时间的是**事后解释与复核**：这条序列里到底有几段异常？每段从哪一行到哪一行？是哪类检测器、用什么窗口和阈值判出来的？换一个人换一台机器，还能不能得到同一批异常点？把结论发给同事时，对方凭什么相信图上的色块不是"画上去的"？

anomaly-atlas 的回答是：**异常集由 run-spec 唯一决定，并由读者自己的浏览器重算出同一个 `sha256`**。做不出这一点，产品就退化成"检测库 + 好看图表"的薄封装。

- 输入：一份 CSV 时间序列（时间戳列 + 数值列，可选 `series_id` 支持多指标）
- 输出：单个 HTML 文件——主序列、异常区间带、峰值标记、缺口纹理、Episode 卡片、多指标 small multiples、异常密度热条；内嵌原始数据与手写 JavaScript 镜像，加载时当场重跑，与构建时指纹逐位一致才显示 **VERIFIED**，不一致显示 **MISMATCH** 并指出首个差异点
- 隐私红线：**数据纯本地处理、零上传**；HTML 零外部请求（无 CDN、无外链字体、无外链脚本）。使用前请自行确认数据可被处理

## 当前状态（诚实口径）

本项目按里程碑推进，**当前已完成 M3 浏览器复算硬门禁**（手写 JS 镜像 + 产物自带数据与指纹 + Node 对账 + 篡改必红并定位），下一步是 M4 单文件标注图。今天真正可用的东西：

```bash
# 源码直跑（Python >= 3.8，零第三方依赖；Windows 用 py 而非 python）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli --help
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli --version

# 数据剖面：CSV -> profile.json（规范 JSON，同输入两跑逐字节一致）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli profile data/samples/minimal.csv -o profile.json
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli profile data/synthetic/series.csv -o profile.json

# 检测：CSV -> run.json（生效参数）/ anomalies.json（Episode + 指纹输入）/ anomaly_set.sha256
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli detect data/synthetic/series.csv --out-dir out
cat out/anomaly_set.sha256

# 基准自检：冻结台账 + 真值全段对账 + 冻结指纹 + 改参数必改哈希 + 双跑一致（各带可证伪探针）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli selftest

# 复算硬门禁：产物自带的手写 JS 镜像在 Node 下重算出同一 sha256（未通过复算的 HTML 不构成交付物）
PYTHONPATH=src py -X utf8 tools/mirror_parity.py --build examples/atlas.html   # 落 M3 最小载体页
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli verify examples/atlas.html      # -> VERIFIED, exit 0
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli verify examples/atlas.html --tamper-index 3   # -> MISMATCH + 定位, exit 1

# 冻结产物自检：manifest 台账 + 重生成逐字节比对（篡改/缺失 -> exit 2）
py -X utf8 tools/gen_synthetic_series.py --check

# 或先 pip install -e .，之后省掉 PYTHONPATH 与 -m 前缀
anomaly-atlas --help
```

`profile` 已按契约落地：坏输入（空文件、缺列 / 列名歧义、时间戳不可解析、数值不可解析、重复时间戳超阈值、时间戳乱序）**一次收集全部错误、每条带源行号或列名、退出码 2**；缺失值记为 `None`，不补 0、不插值。

`detect` 已按契约落地：四类检测器（滚动中位数+MAD、滚动 IQR、自实现 STL 残差、规则型）→ 按**时间域** `max_gap_ms` 合并 → 定点整数严重度排序 → `episode_id`；`run.json` 记录**解析后的生效参数**（含 ACF 估出的 `period_points`、`quant_decimals`、算法与规范版本号），`anomalies.json` 只含整数与字符串，指纹由 `canon.canonical_digest` 单点产出。同一 CSV 两跑逐字节一致；坏 CSV / 坏 spec → 退出码 2 且**零副作用**。

`selftest` 已按契约落地：五项检查（冻结台账 / 真值全段对账 39/39 + 6 条合并探针 / 冻结指纹 / 改参数必改哈希 / 剖面双跑）各带**可证伪探针**，探针不变红即计为失败（exit 1）；找不到冻结数据 → exit 4（不静默通过）。

`verify` 已按契约落地：读出产物**自带**的手写 JS 镜像、内联数据与构建指纹，在 Node 下跑同一流程，与构建值**逐字节比较**（同时逐点比较检测点集合并给出首个差异点）；一致 → VERIFIED（exit 0），不一致 → MISMATCH + 定位（exit 1）。`--tamper-index <n>` 把第 n 个内联样本位移一个大偏移，要求**必变红且首个差异点落在被篡改的那个 series**（否则按探针失败计）。**Node 缺失 → exit 4** 并给两条补救路径，**不静默跳过**。产物不是本契约的产物 → exit 2。

已注册但**尚未落地**的子命令（`render` / `check-report`）当前一律以退出码 **3**（阶段未就绪）返回，**不产出任何假结果**——模块在每个里程碑落地时，同一提交内退役它的就绪标记并补一条离线冒烟。`examples/atlas.html` 现为 **M3 最小载体页**（只做复算徽章），M4 会在同一嵌入契约上把它替换成完整标注图。

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M0 骨架 | plan/02–06 + 包结构 + CLI 退出码契约 + CI 预置 | ✅ 2026-10-17（双解释器 3.8/3.12 各 31 项测试全绿 + 干净 venv 31 项全绿；退出码冒烟 14 条逐条核对；变异验证 4/4 变红；未接远端，CI 待首推验证） |
| M1 数据先行 | CSV 契约、整数时间轴、数据剖面、合成时序与真值冻结 | ✅ 2026-10-17（`profile` 落地并退役退出码 3；211 项测试在 3.8 / 3.12 / 干净 venv 三处全绿；全量 fixture 行被 `datetime` 交叉证伪；真值哈希与冻结产物台账固化；变异验证 10/10 变红；未接远端，CI 待首推验证） |
| M2 检测内核 | 4 类检测器、Episode 合并与严重度排序、规范 JSON 与 sha256 | ✅ 2026-10-17（`detect`/`selftest` 落地并退役退出码 3；411 项测试在 3.8 / 3.12 / 干净 venv 三处全绿，安装面产物与源码直跑逐字节相同；真值全段对账 39/39 + 6/6 合并探针；周期估计 288 与植入一致；冻结指纹 `6020a3d3…`；参数面 20 项"改即变"；无超越函数门实测抓出并修掉 `10 ** d`；变异验证 16/16 变红；未接远端，CI 待首推验证） |
| M3 浏览器复算（硬门禁） | 手写 JS 镜像 + 内联数据 + VERIFIED/MISMATCH + 首个差异点 | ✅ 2026-10-17（`verify` 落地并退役退出码 3；474 项测试在 3.8 / 3.12 / 干净 venv 三处全绿；产物自带镜像在 Node 下重算与构建指纹逐字节相等；`--tamper-index` 覆盖三个 series 均 MISMATCH 且定位到被篡改的 series；SHA-256 与定点规则两组向量双侧断言；变异验证 14/14 变红；退出码冒烟 29 条含 Node 缺失 exit 4 且零副作用；wheel 内含镜像且安装面重建产物与仓库产物逐字节相同；未接远端，CI 待首推验证） |
| M4 渲染 | 单文件标注图（零外链、可打印、灵敏度滑杆） | 未开始 |
| M5 报告门禁 | Episode 命名/原因 + 数字白名单 + SKILL.md/README 定稿 | 未开始 |
| M6 发布 | tag + GitHub Release + 发布留档 | 未开始 |

逐棒的 DoD 与实测证据见 [`plan/05-里程碑.md`](plan/05-里程碑.md)；模块级设计见 [`plan/03-模块详设.md`](plan/03-模块详设.md)；数值口径的唯一权威定义在 [`data/README.md`](data/README.md) §4。

## 确定性声明（本项目的全部卖点）

**模型只做表达层**（数据语义判断、阈值取舍的**理由**、Episode 命名与可能原因、叙事文本），异常点、参数最终值、排序、指纹全部由确定性代码产出。模型不得手改异常点、不得新增未检测到的点、不得在报告中写出未命中 `facts.json` 的数字（由代码门禁而非口头约束）。

落地后以下每个数字都可被独立重算，且哈希验证不需要信任作者机器：

| 数字 / 结论 | 重算方式 |
| --- | --- |
| 数据剖面（节奏、缺口、缺失段、零值段、重复时间戳） | 纯规则计算；同一 CSV 连续两次运行 `profile.json` 逐字节一致 |
| 4 类检测器的判定与得分 | run-spec 里记录解析后的生效参数；异常集由规范 JSON（只含整数与字符串）序列化后取 `sha256` |
| Episode 起止 / 时长 / 峰值 / 源行号 / `episode_id` | 合并口径 = 时间域 `max_gap_ms`；严重度排序键固定（`peak_score_q` → `duration_ms` → `start_row` → `detector`） |
| 浏览器复算结论（VERIFIED / MISMATCH） | HTML 内联原始数据 + 手写 JS 镜像重跑同一套算法 → 规范化 → `sha256` → 与构建指纹逐位比较；同时逐点比较并定位首个差异点 |
| 报告中的每个数字 | 必须命中 `facts.json` 的某条 `fact_id`，未命中即中止并列出上下文 |

哈希可复算的两个前提条件（工程上必须成立，否则复算会随机 MISMATCH）：**规范 JSON 只含整数与字符串**（浮点在哈希边界做整数定点化，禁止浮点格式化参与哈希），以及**检测路径禁用一切超越函数与库归约函数**（只用 IEEE-754 基本运算，幂次展开为乘法）。理由与纪律见 [`plan/02-架构与技术选型.md`](plan/02-架构与技术选型.md) §3 与 `data/README.md` §4.3。

> 表中**数据剖面**一行已由实测覆盖（M1）：同一个 CSV 连续两次 `profile` 输出逐字节一致，且源码直跑与 `pip install -e .` 安装面产出同一份字节。**检测与 Episode**、**run-spec 可复算**两行已由 M2 的 `selftest` 与 `tests/test_detect.py` 覆盖（全段对账、冻结指纹、参数面逐项"改即变"、双跑逐字节）。**浏览器复算结论**一行已由 M3 覆盖：`examples/atlas.html` 里那份手写镜像在 Node 下重算出的规范 JSON 与 sha256 与构建值逐字节相等，篡改一个内联样本必 MISMATCH 且首个差异点落在被篡改的 series（`tests/test_mirror.py` 逐条钉住，含"Node 缺失必须 exit 4"）。剩下**报告中的每个数字**一行仍是目标口径，待 M5 的 `check-report` 落地后补上可直接复制的验证命令与实测证据。

## 使用方式（M1–M3 已落地，其余为计划形态）

```bash
# 1. 数据剖面 + 质量卡（M1 已落地，可实跑）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli profile <你的.csv> -o profile.json

# 2. 检测 → run.json / anomalies.json / anomaly_set.sha256（M2 已落地，可实跑）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli detect <你的.csv> --out-dir out

# 3. 基准自检（M2 已落地，可实跑）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli selftest

# 4. 复算复核（M3 已落地，可实跑；需要 Node；浏览器徽章是人读的那一面）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli verify examples/atlas.html

# 5. 渲染单文件标注图（M4；今天 `render` 仍以 exit 3 表示阶段未就绪）
PYTHONPATH=src py -X utf8 -m anomaly_atlas.cli render <你的.csv> -o atlas.html
```

## 合成数据与真值（M1 冻结资产）

| 资产 | 内容 |
| --- | --- |
| [`data/synthetic/series.csv`](data/synthetic/series.csv) | 长表 `timestamp,series_id,value`，2960 行 = 3 个虚构指标（`temperature` / `humidity` / `energy_kwh`）× 5 分钟网格，含 3 处缺口、3 段缺失、3 段零值、1 个重复时间戳 |
| [`data/synthetic/manifest.json`](data/synthetic/manifest.json) | 生成参数（seed / 网格 / 周期 / 逐指标幅度）+ 逐文件 sha256 台账（生成器实算） |
| [`data/truth/truth.json`](data/truth/truth.json) | 39 段植入真值（每类 ≥2 段、含窗口边界段与 `max_gap_ms` 两侧的合并探针）；**只存输入与期望，无 `observed`** |
| [`data/truth/hash.txt`](data/truth/hash.txt) | 真值异常集按 §4.3 规范 JSON 计算的 sha256 |
| [`data/samples/minimal.csv`](data/samples/minimal.csv) | 17 行手写最小示例（1 处缺口 + 1 个缺失值 + 2 点零值段），可人眼核对 |

冻结纪律与重生成守门：

```bash
py -X utf8 tools/gen_synthetic_series.py --check   # 台账 + 重生成逐字节比对；篡改/缺失 -> exit 2
```

退出码契约：**0** 成功；**1** 门禁/自检发现缺陷（`selftest` 失败、数字白名单未命中、复算 MISMATCH、探针失败）；**2** 用法与输入错误（缺文件、CSV 契约校验失败、未知子命令、产物不合嵌入契约、篡改下标越界）；**3** 阶段未就绪（骨架期标记，随模块落地整项退役；现余 `render`/`check-report`）；**4** 环境前提不满足（如 `verify` 找不到 Node——**不回退、不静默跳过**）。

## 仓库结构

```
SKILL.md                    Agent Skill 主入口（触发条件 / 工作流 / 退出码表 / 模型分工）
src/anomaly_atlas/          cli（编排+退出码+编码守卫）、timebase/csvio/profile（M1）、
                            canon/detect/episodes/selftest（M2）、
                            mirror + mirror/zaa_mirror.js + render（M3：嵌入契约与最小载体页）、
                            layout/render（M4）、facts/report（M5）
tools/                      合成时序与真值生成器（M1）、Node 复算对账 + 载体页构建（M3）
data/README.md              台账 + 数值口径唯一权威定义处（§4：检测器参数 / 合并排序 / 规范 JSON 与哈希 / 错误码 / 数字白名单）
data/synthetic/ data/truth/ M1 冻结产物：合成时序 + 植入真值 + 真值 hash（禁手改）
data/samples/               最小示例 CSV
examples/atlas.html         M3 最小载体页（复算徽章；M4 替换为完整标注图）
tests/                      pytest 套件（含真值对账、双跑一致、零外链、Node 对账与篡改定位、可证伪探针）
plan/                       题目文档、架构、模块详设、数据计划、里程碑、交付对标、决策记录、HANDOFF
```

## 已知环境问题

- **Windows 用 `py` 不用 `python`**：后者常是微软商店占位符。一律 `py -X utf8`（UTF-8 模式防 cp936 控制台编码坑）。
- **双解释器**：本仓库在 Python 3.8 与 3.12 双通道下跑全量测试（`py -3.8` / `py -3.12` 可显式指定）。跨版本差异以 CI 四矩阵为准；"本机能跑"不是跨版本证据。
- **Git Bash 的 `/tmp`**：Windows 原生 Python 看不见 Git Bash 的 `/tmp`，临时文件请用工作区相对路径或系统临时目录。
- **源码直跑 vs 安装跑**：`PYTHONPATH=src` 是源码直跑口径；`pip install -e .` 后 `anomaly-atlas` 命令等价，且该命令只有 Python 标准库依赖（零第三方运行时依赖）。
- **`verify` / `mirror_parity` 需要 Node**（本机实测 `node v24.15.0`；CI 的 windows/ubuntu runner 都预装）：Node 不在时以退出码 **4** 明确失败，并给出两条补救路径（装 Node，或直接在浏览器打开 HTML 看徽章），**不回退、不静默跳过**。JS 镜像随包分发（`anomaly_atlas/mirror/zaa_mirror.js`，wheel 内含），所以安装面同样能跑复算。

## 边界与 roadmap（首期不做）

- 不做通用图表选型/美化：图形只服务异常语义。
- 不做流程挖掘/决策树（DFG、变体、瓶颈属于其他题目）。
- 不做深度学习检测器：首期只做可解释、可复算的统计与规则方法；不引入训练、不引入 GPU，**也不留半成品接口**以免被误认为已支持。
- 不做实时流式监控：只做离线 CSV → 单文件档案，不做常驻服务与告警推送。
- 不做在线渲染/云服务：一切本地；HTML 零外部请求。
- 扩展路线图（不计入首期交付物）：token replay 式流程分析、多指标联动筛选、基准数据集对照。

## 品牌与合规

- 不冒用任何第三方库商标；比较性表述仅作事实引用；仓库名与 Skill 名不含第三方品牌词。
- 合成数据场景明确标注"（虚构）"，不影射真实企业、真实业务数据或真实事件。
- 数据纯本地处理、零上传；HTML 零外部请求。

## License

MIT，见 [LICENSE](LICENSE)。
