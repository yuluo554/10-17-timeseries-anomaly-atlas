# HANDOFF-M5（M4 已收尾 → 下一棒 M5 报告层与数字白名单）

> 用法：新对话 `/goal 读取 <项目绝对路径>\plan\HANDOFF-M5.md 继续完成任务`（库内一律相对路径）。

## 1. 当前进度 + 证据

- **M4 单文件标注图已完成**。今天有真实行为的模块：M1/M2 的全部（`cli`/`timebase`/`csvio`/`profile`/`canon`/`detect`/`episodes`/`selftest`）+ M3（`mirror/zaa_mirror.js` + `mirror.py` + `tools/mirror_parity.py`）+ M4 的 **`layout.py`**（确定性几何与分箱，约 700 行，零浮点输出）与 **`render.py`**（M3 嵌入契约 + 完整标注图：`build_view_html` / `write_view` / `cmd_render` / `assert_no_external_resources` / `assert_no_template_slots`）。仍为 **docstring-only**：`facts`/`report`（不产桩，D14）。
- **`STAGE_NOT_READY` 现余一键** `{check-report:M5}`；`render` 已整项退役（常量 → CLI 接线 → 测试 → 文档 → 决策记录五处同步，见 `plan/06` D22 与 §5 checklist）。**下一棒退役最后一个键后必须删除 `cli.EXIT_NOT_READY` 常量本身**（K1：空后删除；同时 `tests/test_skeleton.py::TestExitCodeContract::test_codes_are_distinct_and_pinned` 与 `TestStageNotReadyRegistry` 两个类要一起改/删——它们现在钉的是五码并存与"每键有名"）。
- **证据（本轮实测）**：
  - 三处全绿：`py -3.12` 78.5 s / `py -3.8` 108.1 s / 干净 venv（3.12 + `pip install -e ".[dev]"`）105.1 s，各 **540 passed, 5 skipped**（5 skip = 未落地命令的 not-ready 用例按设计退役）。
    - **教训**：第一次 3.12 全量跑出 534，是因为*跑完之后*又加了 6 条测试。**加完测试必须重跑三处**，否则"三处全绿"这句话说的是三个不同的代码版本。
  - **`verify` 在新产物上复跑**：`verify examples/atlas.html` → exit 0「VERIFIED」（`6020a3d3…`）；`--tamper-index 3 / 1500 / 2900` 三条各自 MISMATCH 且首个差异点落在被篡改的 series。产物替换（载体页 → 完整标注图）没有动嵌入契约，所以 `mirror.py` 的判定实现零改动。
  - **浏览器通道实测**（人读那一面；本机内置浏览器**不支持 `file:` 导航**，故用本地回环 `http.server` 打开）：徽章绿色 **VERIFIED**（`card verified`、`rgb(23,128,61)`、22.4 px、两串指纹相同、首个差异点"无"）；**滑杆基线（100% / 1800000）复算 == 构建指纹**；`k_scale=150` → 582 点 / 166 段、`k_scale=50` → 1276 点 / 350 段、`max_gap_ms=3600000` → **248 段**；滑杆全程**不覆盖**徽章与构建指纹；run-spec 片段显示 `k="5.250000"`；`@media print` 的规则从 CSSOM 复核（`break-inside: avoid` + `.controls { display: none }`）；**`performance` 资源条目 0**，本地服务访问日志只有一次文档 GET。
  - **图上"有墨"用几何证据核验**（截图分辨率不足以判读 1 px 线宽，M3 已有同类记录）：主序列首段折线 `getTotalLength()=2568`、band/polygon/hatch 的 `getBBox` 均为正整数尺寸、178 张 Episode 卡片、84 个密度格、199 个内联 SVG。
  - **变异验证 20/20 变红**（每条三条断言：marker 唯一 → 字节已变 → 还原一致）。靶子覆盖题面要求的那四类：改像素映射分母 / 去掉 y 轴 padding / 抽掉缺口条纹 / 让零值段冒充缺口纹 / 改分箱边界 / 静态阈值丢符号 / 去掉 render-spec 守卫 / 去掉最小带高 / **去掉出口零外链断言** / **去掉出口无 `$` 断言** / **让滑杆越过 JS 内核自己算** / 抽掉缺失段虚线 / `@media print` 改 screen / 灰阶档位去填色 / 浅色渲染不钉 / 主序列 tie-break 反向 / `build_id` 写死 / 叙事不转义 / 卡片阈值说明置空 / 页面写死默认呈现参数。
    - **一次真实发现（M02）**：去掉 y 轴 padding 的变异**最初仍绿**——因为测试里写的是不等式（`low < 0 < high`），而"padding 退化成 1 个定点单位"也满足它。把断言改成字面量（`value_bounds([0, 1000000]) == (-40000, 1040000)`）后才变红。**不等式的断言常常只钉住了退路，没钉住规则**。
  - 退出码冒烟 **38 条逐条实测**（0/1/2/3/4 全五档，15/2/18/1/2 条）：含 `render` 未知 spec 键 → 2、未知 render 键 → 2、叙事含 `$` → 2、坏 CSV → 2、`--spec` 缺文件 → 2、`check-report` → 3、`--node no-such-node` → 4；失败路径**零副作用**（38 条前后全仓文件快照差集为空、失败路径没有留下任何命名产物）。
  - **安装面**：干净 venv 的裸 console script `anomaly-atlas render` 重建的产物与仓库内 `examples/atlas.html` **逐字节相同**（832052 B）；`verify` exit 0；`selftest` 5 check / 0 failing。
- **诚实口径**：**未接远端，CI 待首推验证**。CI 已补四步 M4 冒烟（`render` 双跑逐字节 + 出口两条断言复核 + 裸 console script `render` + 新产物 `verify`），**均未实跑**；ubuntu/windows 腿与 CI 步骤形态仍属本地等价校验缺口。

## 2. 下一棒待办（M5 报告层与数字白名单）

1. **`facts.py`：事实台账（`facts.json`）**。每条数字一个 `fact_id`（例如 `episodes.total` / `episode.<episode_id>.peak_score_q` / `series.<id>.n_gaps` / `bin.<k>.coverage_q` / `detection.<series>.<detector>.n_points`）；**键排序落盘 + 规范 JSON**（复用 `canon.canonical_json_bytes`，K2/K3）；数值形态与 `run.json` 一致（定点串/整数，禁浮点）；`fact_id` 与值的映射必须**唯一**（两个 fact 同 id 或同值不同 id 都要有测试钉住）。
   - 数据来源全部是已有结论（`anomaly_set` / `run_document` / `profile`），**不得**新算任何判定；`facts.py` 不读 CSV、不调检测器。
   - 台账要覆盖题面评分点需要的数字：异常数、每段峰值/时长/起止行号/检测器、每检测器流的点数、缺口/零值/缺失段计数、密度热条分箱覆盖度、数据质量计数。
2. **`report.py`：数字白名单门禁（`check-report`）**。
   - `extract_numbers(text)` → 数字 token：阿拉伯数字（含千分位、百分号、小数、科学计数法形态）+ **中文数字形态**（一/二/三…十/百/千/万、以及"三处"这类量词搭配）；token 要保留**上下文片段**便于报错。
   - `check_report(text, facts)` → 未命中清单（token + 上下文 + 最接近的 fact 值），未命中即 **exit 1** 并逐条打印，**不生成报告**。
   - **Episode 引用可解析**：叙事里出现的每个 `episode_id` 形态（正则 `[A-Za-z0-9_]+-E\d{3}`）都必须能在 `anomalies.json` 里解析到；引用不到 → exit 1。
   - **"模型禁区"由代码门禁而非口头约束**（题面 M1.1/M5）：叙事不得引入异常集之外的 episode、不得出现新的行号（`row N` / `行 N` 形态的行号必须命中档案里出现过的行号或明确标为"文件行/CSV 行"的既有引用）。
   - CLI 接线已预置（`cli.py` 的 `p_check_report`：`--facts` + `--text`，输入前置检查已在注册表里）；实现 `cmd_check_report(facts_path, text_path)` → 0/1/2（缺文件/坏 JSON/未命中区分：**缺文件与坏 JSON 是 2，未命中是 1**）。
3. **`check-report` 落地 → K1 退役第三步**（同一提交内五处同步）：`STAGE_NOT_READY` 删最后一个键 → **删除 `EXIT_NOT_READY` 常量** → CLI 接线（已预置）→ 测试（`test_skeleton.py` 的注册表/五码断言/not-ready 用例要一起改：注册表清空后那个参数化用例全部 skip，或整类退役并换成"没有任何命令答 3"的正向断言）→ README 与 `plan/00·02·03·05` 状态表 → 决策记录补一条（D23）。
4. **SKILL.md**（题面要求的主入口）：触发条件、四步工作流（`profile` → `detect` → `render` → 指读 HTML + 徽章）、**模型分工声明**（模型只做表达层：语义判断、阈值取舍理由、Episode 命名与可能原因、叙事；异常点/参数/排序/指纹全部由代码产出）、输入 schema（CSV 列角色与时间戳形态）、退出码表（**M5 之后应只剩 0/1/2/4**，3 已全线退役）、复算口径段（内联镜像 + Node 对账 + 徽章）。
5. **README 定稿**：把"当前状态/使用方式/确定性声明/已知环境问题"逐条与实物对齐（尤其"哪些命令可跑"、"如何验证哈希"、"报告数字如何被门禁拦住"三处要能**逐字复制执行**）；README 里出现的每个数字都要能在仓库里找到出处。
6. **`plan/自评表.md`**：题面评分四栏（40/20/20/20）自评表，每栏逐项挂证据（测试名 / 命令 / 实测输出）。
7. **收尾**：DoD 验证（双解释器 + 干净 venv + **变异验证**，靶子要挑对：改 `facts` 数值口径 / 让 `check-report` 放过一个编造数字 / 让 episode 引用不可解析仍通过 / 只报首个未命中而不报全部）→ `plan/00·02·03·05·06` 状态回写 → 写 `plan/HANDOFF-M6.md` → 删除临时目录与 venv → commit。

## 3. 既定口径清单（K，动了会打挂测试）

- **K1 退出码契约（D8）**：0 成功 / 1 门禁或自检发现缺陷 / 2 用法与输入错误 / 3 阶段未就绪 / 4 环境前提不满足。`STAGE_NOT_READY` 现为 **`{check-report:M5}`**；落地一个键**整项退役**、五处同步；**空后删除 `EXIT_NOT_READY` 常量**并按上文改造测试。
- **K2 序列化冻结**：JSON 落盘统一走 `canon.canonical_json_bytes`（`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行，**注意实现里 `json.dumps` 的 `sort_keys=True` 就是键排序**）；**产物里禁时钟字段**；`profile.json`/`run.json`/`facts.json` 里不得有 ISO 串（ISO 只出现在 `anomalies.json` 的 Episode `start`/`end`）。
- **K3 规范 JSON 只含整数与字符串**：`canon.assert_hashable` 在落盘出口拒浮点；`quantize` 半偶舍入（默认 6 位）、`fixed_to_str` 由整数构造十进制串；十进制的检测器参数以 6 位定点串落盘；**内联样本也走这条规则**（K20）。
- **K4 数值可镜像**：哈希/判定路径只允许 `+ - * / floor ceil abs min max` 与比较；幂次展开为连乘；**禁一切超越函数与库归约函数**。门在 `tests/test_no_transcendental.py`（AST + 词法 + 豁免表 + 变异）。**`layout.py` 通过这道门**（它只用整数除法/乘法与 `detect` 的私有口径函数，未新造统计）。注意该门的 AST 细节：`ast.Pow` 是算符节点无 `lineno`，要检测 `**` 得看 `ast.BinOp(op=Pow)` 与 `ast.AugAssign(op=Pow)`。
- **K5 时间口径**：UTC 整数 epoch 毫秒；落盘 ISO 定点串由整数反算；小数秒截断；镜像不重实现时间解析。**M4 补充**：密度热条的分箱按整数毫秒切分，`density_bins` 用行号回查 `row_no → epoch_ms`（不走 ISO 解析，不给渲染路径加时区库）。
- **K6 排序与 tie-break**：所有排序给全序比较器（含源行号 index tie-break）；Episode 严重度键 = `peak_score_q` 降 → `duration_ms` 降 → `start_row` 升 → `detector` 字典序；`episode_id = "<series_id>-E<NNN>"`（按 series 计数）。**M4 补充**：主序列的选择规则 = Episode 数最多、并列取 `series_id` 字典序最小（`render._primary_series`）。
- **K7 Episode 合并**：时间域 `max_gap_ms`；相邻异常点时间差 **≤** 该值即合并；按 `(series_id, detector)` 分组；与剖面的"缺口区间"是两个概念。**M4 的滑杆允许把 `max_gap_ms` 抬到两倍看合并效果，但那只是页面上的复算视图**，不改档案。
- **K8 参数面与生效值**：`run.json` 记录解析后的最终值；复算侧消费生效值、不重跑估计；引擎里不留隐形默认；**生效参数块在异常集指纹里**。**M4 的边界（D22）**：`pad_rows` / `heat_bin_ms` 是**呈现**参数，走 render 自己的 run-spec 并记录在产物页面上，**不进** `run.json`、不进指纹——理由是"改一个与判定无关的呈现旋钮不应改档案指纹"。这条是**对 HANDOFF-M4 §2.1/§5 "pad/heat_bin_ms 进 run-spec" 字面要求的刻意偏离**，已在 `plan/06` D22 与 `plan/03` M4 落地口径里写明；若 M5 认为必须回到字面要求，那是一处需要同步改 D22、`layout.resolve_render_spec`、`render` 的 spec 拆分与三处测试的**大改**，不要顺手改。
- **K9 数据契约与错误码**：`csvio.ERROR_CODES` 单点定义（7 个）+ 文档表互等门；行号 = 物理行号；一次报全部错误；缺失标记 → `None`（不补 0 不插值）。
- **K10 编码守卫**：`cli.py` 是 `_ensure_utf8_stdio()` 的单点定义，`tools/` 下每个可执行入口导入并调用它（**新增脚本必须补挂**）；子进程读写显式 `encoding=`；CI env `PYTHONUTF8=1`。
- **K11 生成器纪律**：splitmix64 自研 RNG；seed 显式传参并写 manifest；`--check` 两层断言；真值只存输入与期望、禁 `observed`；生成器断言真值非平凡且可检出。
- **K12 零外链**：`render` 出口常驻 `assert_no_external_resources(html)`；**HTML 加载时不得发起任何网络请求**。现有实现：先屏蔽脚本体再扫标记（`http(s)://` / `src=` / `href=` / `<link>` / `<iframe>` / `@import` / `integrity=` / 协议相对 `//`），同时扫脚本体里的网络 API；`url()` 只放行 `data:`。**M4 的后果**：`<svg>` 不能带 `xmlns="http://..."`（会被 `http://` 命中），也不能用 `href=` / `xlink:href` / `<use>` / `clip-path: url(#id)`；三类纹理因此做成显式线段/竖栅/虚线框（`plan/03` M4 落地口径）。
- **K13 复算指纹一致性**：`canonical_json_bytes`/`quantize`/`fixed_to_str`/`sha256_hex`/`canonical_digest` 是**唯一**实现；JS 镜像必须逐字节产出同一份规范 JSON；未通过 Node 对账的 HTML 不构成交付物。
- **K14 数字白名单**：报告数字必须命中 `facts.json`（M5 落地）。
- **K15 不留桩（D14）**：未落地模块不产 `NotImplementedError`/`pass`/`return 0` 桩；`tests/test_skeleton.py::TestNoSentinelStubs` 常驻扫描 `src/`+`tools/` 的 `.py`/`.js`（含正向对照与变异）；**注释也会被扫**（别写 `placeholder` / `NotImplementedError` / `TODO: 实现` 这三个串；M3/M4 都为此红过一次）。
- **K16 命令注册表三处同步**：`cli.COMMANDS` / `cli.STAGE_NOT_READY`（M5 后应为空）/ 测试侧 `_ARGS_BY_COMMAND` + `_INPUT_FILES`。
- **K17 冻结数据的已知形状**（post-D19）：长表按 (时间, series) 交错（同一 series 相邻行号差 3）；温度行含 1 个重复时间戳；四种时间戳表示成块交替；缺失写成空串、零值写成 `0.00`；每 series 各有 1 处时间缺口；humidity 噪声幅度 200 milli。**M4 实测补充**：3 个 series 各 985/987/988 行；每 series 恰好 1 缺口 + 1 零值段 + 1 缺失段（所以"三类纹理各有其一"可以直接在冻结数据上断言）；1 小时的 `heat_bin_ms` 得 84 箱。
- **K18 指纹黄金值与探针方向**：异常集指纹 `6020a3d3…` 钉在 `selftest.GOLDEN_ANOMALY_DIGEST`、`tests/test_detect.py`、`tests/test_mirror.py`、`tests/test_render.py` 多处；任何检测算术或数据改动都会让它变红——这是**故意的跳线**。**M4 的呈现参数刻意不碰它**（D22），所以"完整标注图与 M3 载体页带同一个指纹"本身就是 D22 的实测证据。探针必须**增加**一项无法满足的要求（删段只会让要求一起消失）。
- **K19 "39 段"不是"39 个 episode"**：探针两侧的"25 分钟"三对必须合并；对账判据是**覆盖**而非数量相等。当前默认 spec 全量输出 178 episodes / 653 detections（7 条检测器流）。
- **K20 嵌入契约四条铁律**：① 内联样本是十进制文本（`repr` 最短往返串；镜像用 `parseFloat` 最近双精度还原），整份 payload 仍过 `canon.assert_hashable`；② 三块 `<script id>` = `zaa-payload`/`zaa-mirror`/`zaa-boot`，**块体前后不加换行**（"产物里那段镜像源码与 `zaa_mirror.js` 逐字节相等"有测试钉住）；③ **产物里不得出现任何 `$`**（`render.assert_no_template_slots` 常驻渲染出口；`--narrative` 里带 `$` 在 CLI 层就 exit 2）；④ `verify` 与 `tools/mirror_parity.py` **共用 `mirror.verify_artifact`**。
- **K21 红必须能指认自己**：篡改探活打内联数据（series 存储序 + 行序），要求"必变红 **且**首个差异点落在被篡改的 series"，否则 exit 1。**指纹相等不是定点规则的正确性证据**（改半偶边界在冻结指纹上实测仍全绿），定点规则另有跨语言向量门（`mirror.FIXED_POINT_VECTORS`）。
- **K22 Node 前提**：Node 缺失 → exit 4 + 两条补救路径，不静默跳过；产物不合契约 → exit 2；镜像跑不起来 → exit 1。本机有 Node（v24.15.0）；CI 第一步显式 `node --version` 断言。
- **K23（M4 新增）呈现与判定分家**：见 K8 的 M4 条目（D22）。`render` 的 `--spec` 是"检测 run-spec + 可选的 `"render"` 块"，`render.split_spec` 负责拆；未知检测键与未知呈现键都是 exit 2。
- **K24（M4 新增）几何全整数 + 纹理是结构**：`layout` 的所有返回值里**没有浮点数**（`tests/test_layout.py` 用 `conftest.iter_floats` 逐层断言）；行号 → 像素 = `left + index * plot_width // (n-1)`，坐标取整；三类异常区用**三种结构**（斜纹线段 / 竖栅 / 虚线框），不靠色深；时间缺口按缺席样本数就地加宽（映射不动）。
- **K25（M4 新增）产物出口两条断言**：`assert_no_external_resources` + `assert_no_template_slots`，都在 `build_view_html` 的出口常驻（每次渲染都跑）。**M3 的教训**是"Node 通道绿 ≠ 人读那一面成立"，所以这两条断言必须能被**注入式**测试证伪（`tests/test_render.py::TestTheBuilderAssertsAtItsOwnExit` 用 `--narrative` 注入外链与 `$`）。
- **K26（M4 新增）滑杆只改显示**：滑杆重算必须走产物内联的同一份 JS 内核；**基线下复算必须等于构建指纹**；滑杆结论与构建指纹**分块显示**、互不覆盖；滑杆值渲染成 run-spec 片段（走 `ZAA.canonicalJsonText`）。M5 若把 facts 也搬进页面，注意不要破坏这条分块。
- **K27（M4 新增）页面固定浅色**：`:root { color-scheme: light }` 有测试钉住（打印是目标形态，色深/灰阶在纸上的含义必须与屏幕一致）。

## 4. 本机环境坑（只写实测过的）

- 用 `py` 不是 `python`；一律 `py -X utf8`。本机 **3.8.8 与 3.12.10** 两条通道；每棒双解释器全量跑。
- 全程 `PYTHONDONTWRITEBYTECODE=1`；源模式跑测：`PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest tests/ -q`。
- 全量套件时长（本轮实测）：3.12 78.5 s / 3.8 108.1 s / 干净 venv 105.1 s（差异主要来自 Node 子进程与载荷构建，别把单次时长当跨版本证据）。
- **加完测试要重跑三处**：本轮 3.12 先跑出 534，之后又加了 6 条测试——**数字必须来自"最后一份代码"**。
- pip 装包必须 `NO_PROXY="*" no_proxy="*"` + 清华镜像；`py -3.12 -m venv .venv-verify` + `pip install -e ".[dev]"` 一次成功；**验证用 venv 用完立刻删**。
- **`py -3.12 -m venv` 里没有 setuptools**：想在本机打 wheel 必须先 `pip install setuptools wheel`（否则 `pip wheel --no-build-isolation` 报 `BackendUnavailable`）。
- Git Bash 的 `/tmp` 与 Windows 原生 Python 不通：临时文件用仓库内相对目录（`.tmp/`，已 gitignore）。
- **本机有 Node v24.15.0**；`verify` 的 Node 缺失分支用 `--node <不存在的名字>` **确定性**触发。
- **`pytest` 的 `capsys` 是 function-scoped**：不要塞进 module-scoped fixture（会 `ScopeMismatch`）。
- **测试提速**：载体重建一次约 1.9 s（解析 + 一次全量检测 + 渲染），所以 `test_render.py` / `test_mirror.py` 的 module fixture 都用 `detect.detect_all_detailed` 把**同一趟**的 detections 直接交给 `build_view_html(..., detections)`——重跑检测器会让每个用例多花 ~1.6 s。
- **哨兵扫描器连注释一起扫**：命中 `placeholder` / `NotImplementedError` / `TODO: 实现` 即红——注释里解释"模板槽位"时**别写那个英文词**（写 "slot"）。
- **变异脚本必须三连断言**（替换前 marker 唯一 → 替换后字节已变 → 还原后字节一致），且**要挑对靶子**：靶子写错会出现"改了指了另一个测试也绿"或"变异本身是空操作"两种假绿。**第二条实测教训**：把规则断成**不等式**往往只钉住退路不钉住规则（M02：去掉 y 轴 padding 后 `low < 0 < high` 仍成立）——能写字面量就写字面量。
- **浏览器通道**：ZCode 内置浏览器（IAB 后端）**不支持 `file:` 导航**（`goto()` 只接受 http/https/about:blank）。要在浏览器里验产物，用本地回环服务：`py -3.12 -m http.server 8731 --bind 127.0.0.1`，然后开 `http://127.0.0.1:8731/examples/atlas.html`；**验证完记得按 PID 杀掉**（`netstat -ano | grep :8731` → `taskkill //F //PID <pid>`）。截图通道分辨率不足以判读 1 px 线宽，**"图上有墨"要用 DOM 几何证据**（`getBBox()` / `getTotalLength()` / 元素计数）；打印样式从 **CSSOM** 读（`document.styleSheets[...].cssRules` 里 `conditionText === "print"` 的那条规则）。
- **`tab.playwright.locator(...).screenshot` 不存在**（要区域截图得走 `tab.cua.*` 或整页 `tab.screenshot()`）。

## 5. DoD 逐项 checklist（M5 出口）

- [ ] `facts.py`：每条数字带唯一 `fact_id`、键排序 + 规范 JSON 落盘、无浮点；覆盖异常数/每段峰值时长行号/每检测器流点数/缺口与零值缺失计数/热条覆盖度/质量计数；有"id 唯一"与"值可被独立复算"的测试
- [ ] `report.py`：`extract_numbers` 覆盖阿拉伯 + 中文数字形态；`check_report` 未命中即 exit 1 并**列出全部**未命中（token + 上下文 + 最接近 fact）；episode 引用可解析门 + 不得引入新 episode/新行号；缺文件/坏 JSON → 2
- [ ] `check-report` 落地并**整项退役退出码 3**（含删除 `EXIT_NOT_READY` 常量）：五处同步 + 测试改造 + CI 同提交补 `check-report` 离线冒烟（命中 → 0 / 注入编造数字 → 1）
- [ ] `SKILL.md`（触发条件 / 四步工作流 / 模型分工 / 输入 schema / 退出码表 / 复算口径）+ README 定稿（可跑命令逐字可执行、数字有出处）
- [ ] `plan/自评表.md`（四栏自评 + 每项挂证据）
- [ ] 三处全绿（3.8 / 3.12 / 干净 venv）+ 退出码冒烟逐条实测（含零副作用，**3 档应已不存在**）+ **变异验证（靶子挑对）** + **浏览器打开一次**（两通道各验一次：Node 对账 + 页面文本/CSSOM/零请求）
- [ ] `plan/00·02·03·05·06` 状态回写 + `plan/HANDOFF-M6.md` 六节齐落盘并 commit
- [ ] CI 首推全绿 —— **未接远端，待 M6 首推验证**（不可本机实跑；ubuntu/windows 腿与 CI 步骤形态是本地等价校验的缺口）

## 6. 关键命令速查

```bash
cd <repo>
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1

py -3.12 -X utf8 -m pytest tests/ -q          # 全量测试（3.8 同；约 79 s / 108 s）
py -3.12 -X utf8 -m pytest tests/test_layout.py tests/test_render.py tests/test_mirror.py -q

py -3.12 -X utf8 -m anomaly_atlas.cli detect data/synthetic/series.csv --out-dir out
cat out/anomaly_set.sha256                     # 6020a3d3…
py -3.12 -X utf8 -m anomaly_atlas.cli selftest # 5 检查 + 5 探针，全绿 → exit 0

# M4 标注图（产物替换后用同一条命令重建，与仓库产物逐字节相同）
py -3.12 -X utf8 -m anomaly_atlas.cli render data/synthetic/series.csv -o examples/atlas.html
py -3.12 -X utf8 tools/mirror_parity.py --build examples/atlas.html   # 同一件事的工具入口

# M3 复算门禁（本机有 Node）
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html      # VERIFIED, exit 0
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html --tamper-index 3   # MISMATCH + 定位, exit 1
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html --node no-such-node # exit 4 + 两条补救路径
py -3.12 -X utf8 tools/mirror_parity.py --html examples/atlas.html    # 同一判定的工具入口

# 浏览器人读面（IAB 不支持 file:，走本地回环；验完按 PID 杀掉）
py -3.12 -X utf8 -m http.server 8731 --bind 127.0.0.1 &
#   开 http://127.0.0.1:8731/examples/atlas.html
netstat -ano | grep :8731        # 找 PID
taskkill //F //PID <pid>

# 安装跑法（本机实测一次成功；验证完删 venv）
py -3.12 -m venv .venv-verify
NO_PROXY="*" no_proxy="*" ./.venv-verify/Scripts/python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv-verify/Scripts/python.exe -m pytest -q
./.venv-verify/Scripts/anomaly-atlas.exe render data/synthetic/series.csv -o .tmp/venv-atlas.html
#   实测：与 examples/atlas.html 逐字节相同（832052 B）
./.venv-verify/Scripts/anomaly-atlas.exe verify examples/atlas.html
rm -rf .venv-verify
```
