# HANDOFF-M6（M5 已收尾 → 下一棒 M6 发布与远端对账）

> 用法：新对话 `/goal 读取 <项目绝对路径>\plan\HANDOFF-M6.md 继续完成任务`（库内一律相对路径）。

## 1. 当前进度 + 证据

- **M1–M5 全部落地，六个子命令全部真实可跑**：`profile` / `detect`（含 `facts.json`）/ `selftest`（6 检查 + 6 探针）/ `verify` / `render`（含 `--narrative` 门禁）/ **`check-report`**。今天的 M5 新增：`facts.py`（台账）、`report.py`（数字 + episode 引用 + 行号三门）、`detect` 落 `facts.json`、`render --narrative` 构造期门禁、`selftest` 第 6 项检查、`SKILL.md`、README 定稿、`plan/自评表.md`。
- **退出码 3 已整项退役**：`cli.STAGE_NOT_READY = {}`（空注册表）、**`cli.EXIT_NOT_READY` 常量已删除**、CLI 的 not-ready 分支已删、`tests/test_skeleton.py::TestStageNotReadyRegistry` **整类退役**换成 `TestExitCodeThreeIsRetired`（跑遍每个命令断言"没有任何命令答 3"）、CI 加同款断言。现行契约 = **0 / 1 / 2 / 4**。**M6 不要再加任何退出码**——五档变四档是 M5 的收口结果，回退等于把骨架期语义带进发布版。
- **证据（本轮实测，全部来自"最后一份代码"）**：
  - **三处全绿、0 skip**：`py -3.12`（127.5 s）/ `py -3.8`（145.5 s）/ 干净 venv（3.12 + `pip install -e ".[dev]"`，62.4 s），各 **602 passed, 0 skipped**。三个数字都来自加完测试后的重跑；单次时长的差异主要来自机器负载（3.12 那一跑前后还跑过别的重活），**别把单次时长当跨版本证据**。
  - **`facts.json`**：`detect --out-dir` 现在落 4 个文件（run.json / anomalies.json / facts.json / anomaly_set.sha256）。台账实测 **1861 条事实（1682 数值 + 179 文本）/ 178 个 episode id / 138 个档案行号 / 84 个分箱**，321 KB 上下；只含整数与 6 位定点串（`_check_value` 入口拦类型 + `canon.assert_hashable` 出口拦浮点），**无 ISO 串**（Episode 起止以 `start_ms`/`end_ms` 落盘），键排序 + 同输入两次构建**逐字节相同**。
  - **门禁双向可证伪**：干净叙事 `check-report` exit 0；编造数字（`987654321`）/ 编造 episode（`nonesuch-E777`）/ 档案外行号（`row 987654321`）**逐条列出**（token + 偏移 + 上下文 + 最接近的事实）并 exit 1；`render --narrative` 在**构造期**跑同一门禁，未通过 **exit 1 且一个字节都不写**（实测产物不存在）。
  - **变异验证 27/27 全红**，每条都**指名了变红的测试**，三条断言（marker 唯一 → 字节已变 → 还原逐字节一致）全过。**另抓出 3 条测试侧缺陷**（已修）：(a) 百分号比值那条断言写成"违规 token 里不含某 fact_id"——**不可能失败的断言**；(b) episode 门改用 series id 时，挑的"编造即拒绝"测试**仍绿**（编造的 series 也不在 series 表里），真正能区分的是"真引用必须通过"那一类——**靶子必须挑到能区分的断言上**；(c) `facts.json` 形状检查漏 `catalog` 原本没有测试覆盖（补了"缺 catalog 必须 exit 2"）。
  - **退出码冒烟 43 条逐条实测**：16×0 / 8×1 / 17×2 / 3×4，**没有一条答 3**；失败路径**零副作用**（每条前后全仓文件快照差集为空，`render` 拒收叙事时产物不落地）。脚本留在 `.tmp/smoke.py`（未提交，`.tmp/` 已 gitignore）。
  - **浏览器通道实测**（本地回环 `http.server`，人读那一面）：带叙事的产物徽章绿色 **VERIFIED**（`#verdict-label=VERIFIED`、`getComputedStyle` `rgb(23,128,61)` / 22.4 px、两串指纹相同、首个差异点"无"）；**报告区**显示 `叙事（--narrative，已通过数字白名单门禁）` + 白名单横幅（`4 number(s), 1 episode reference(s), 2 row reference(s) 全部命中 facts.json（1861 条事实，178 个 episode_id 可解析）`）+ 叙事原文；仓库产物（无叙事）报告区显示新引导文案；两页 `performance` 资源条目 **0**、本地服务访问日志**每次导航只有一次文档 GET**；CSSOM 里 `@media print` 实测生效（`.card/.episode/.chart {break-inside: avoid}`、`.controls {display: none}`）；178 张 Episode 卡片 / 199 个内联 SVG / `:root{color-scheme:light}`。
  - **README 的 check-report 两行逐字复制执行过**（在 `.tmp/readme/` 里真跑）：干净 → exit 0，编造 → exit 1 并打印 MISS。`examples/atlas.html` 因报告区文案变化**已重建**（832179 B），`verify examples/atlas.html` → exit 0「VERIFIED」（`6020a3d3…`）。
- **诚实口径**：**未接远端，CI 待首推验证**。CI 本轮补了 5 步 M5 冒烟（`check-report` 命中 → 0 / 注入编造数字 → 1 且列出 / 裸 console script / `render` 拒收编造叙事且零产物 / "注册表为空且常量已删"），**均未实跑**；ubuntu/windows 腿与 CI 步骤形态仍属本地等价校验缺口 —— **这正是 M6 第一件要收的事**。
- **两条留在文档里的边界（不是缺陷，是口径）**：数字白名单是**值级**门禁——一个恰好等于某条事实的编造数字能过（保证"有出处"，不保证"用对了地方"）；`selftest` 的 exit 4 从命令行只能用"仓库外的一份包副本 + 仓库外 cwd"触发（源码/editable 安装的 `_PACKAGE_ROOT` 指向仓库根），另有单测 monkeypatch 覆盖。

## 2. 下一棒待办（M6 发布与远端对账）

1. **建仓并首推**：`gh` 通道，账号 `yuluo554`，仓库名 `10-17-timeseries-anomaly-atlas`，**public**（`plan/06` P1 的推荐默认，用户未答复即按此执行；`plan/06` P2 亦规定"M1–M5 全部完成后单独一棒走 M6"）。首推后**逐条核对 CI**：四矩阵（windows/ubuntu × 3.8/3.12）是否全绿；若有红，**先修 CI 步骤形态**再继续（本地等价校验过了不代表 runner 上过——runner 的 Node 版本、路径分隔符、`pip` 镜像策略都可能不同）。
2. **数据库式对账**：每个 push/tag 事件**恰一次** CI run 且 `head_sha` 全对上。用 `gh api` 拉 push 事件与 run 列表，做成一张对账表（事件 sha → run id → 结论），落进 `plan/RELEASE-M6.md`。
3. **发布三件套**：
   - `git tag vX.Y.Z`（版本号与 `pyproject.toml` / `anomaly_atlas.VERSION` 一致——`tests/test_skeleton.py::TestVersionConsistency` 已经在钉这条）；
   - GitHub Release：附 `examples/atlas.html`（成品）+ 基准数据（`data/synthetic/series.csv`、`data/synthetic/manifest.json`、`data/truth/truth.json`、`data/truth/hash.txt`）+ 真值 sha256 与异常集指纹的说明；
   - `plan/RELEASE-M6.md` 留档：tag、Release URL、产物 sha256、CI 对账表、已知环境问题摘要。
4. **发布物本体已验**：把 Release 附件下载回来，`verify` 下过的 HTML（exit 0 / VERIFIED），确认附件 sha256 与本地产物一致；`selftest` 在 clone 后的新目录里跑一次（这条同时验"clone 即用"）。
5. **`git archive`/`.gitattributes` 复核**：一切快照 LF + UTF-8 无 BOM 是否在 tag 里成立（`data/README.md` §5 的冻结纪律依赖这一点）。
6. **收尾**：`plan/00·02·05·06` 状态回写（M6 行）→ 写 `plan/HANDOFF-RELEASE.md`（或直接收束，看是否还有下一棒）→ 删除临时目录与 venv → commit。**注意**：发布后不要再改 `data/`（冻结资产）或 `examples/atlas.html`（复算门禁的基准产物）；要改就得走一遍生成器 `--check` 与三处全绿。

## 3. 既定口径清单（K，动了会打挂测试）

- **K1 退出码契约（D8 + D23）**：**0 成功 / 1 门禁或自检发现缺陷 / 2 用法与输入错误 / 4 环境前提不满足**。**没有 3**：`STAGE_NOT_READY` 为空注册表、`EXIT_NOT_READY` 常量已删除；`tests/test_skeleton.py::TestExitCodeThreeIsRetired` 与 CI 各有正向断言"没有任何命令答 3"。**回退或新增一档都会打挂这两处。**
- **K2 序列化冻结**：JSON 落盘统一走 `canon.canonical_json_bytes`（`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行）；**产物里禁时钟字段**；`profile.json`/`run.json`/**`facts.json`** 里不得有 ISO 串（ISO 只出现在 `anomalies.json` 的 Episode `start`/`end`）。
- **K3 规范 JSON 只含整数与字符串**：`canon.assert_hashable` 在落盘出口拒浮点；`quantize` 半偶舍入（默认 6 位）、`fixed_to_str` 由整数构造十进制串；**台账里十进制值一律 6 位定点串**（与 `run.json` 同形态）。
- **K4 数值可镜像**：哈希/判定路径只允许 `+ - * / floor ceil abs min max` 与比较；幂次展开为连乘；**禁一切超越函数与库归约函数**。门在 `tests/test_no_transcendental.py`（AST + 词法 + 豁免表 + 变异）——**它扫 `src/` 全包，也包括 `selftest.py`**：本轮就因为在 selftest 里写了 `10 ** d` 而红过一次，改用 `facts.scaled_value` 才对。注意 `ast.Pow` 是算符节点无 `lineno`，检测要看 `ast.BinOp(op=Pow)` 与 `ast.AugAssign(op=Pow)`。
- **K5 时间口径**：UTC 整数 epoch 毫秒；落盘 ISO 定点串由整数反算；小数秒截断。台账用 **`start_ms`/`end_ms`（整数）**；`report` 侧把叙事里的 ISO 时间戳换算成毫秒再与台账比对（这正是"照页面上的时间引用"能被接受的原因）。
- **K6 排序与 tie-break**：所有排序给全序比较器（含源行号 tie-break）；Episode 严重度键 = `peak_score_q` 降 → `duration_ms` 降 → `start_row` 升 → `detector` 字典序；`episode_id = "<series_id>-E<NNN>"`（按 series 计数）。主序列 = Episode 数最多、并列取 `series_id` 字典序最小。
- **K7 Episode 合并**：时间域 `max_gap_ms`；相邻异常点时间差 **≤** 该值即合并；按 `(series_id, detector)` 分组；与剖面的"缺口区间"是两个概念。**滑杆允许把它抬到两倍看合并效果，但那只是页面上的复算视图**，不改档案。
- **K8 参数面与生效值**：`run.json` 记录解析后的最终值；引擎里不留隐形默认；**生效参数块在异常集指纹里**。**M4 边界（D22）**：`pad_rows` / `heat_bin_ms` 是**呈现**参数，走 render 自己的 run-spec 并记录在产物页面上，**不进** `run.json`、不进指纹——对 HANDOFF-M4 §2.1/§5 字面要求的刻意偏离，已在 D22 与 `plan/03` M4 落地口径写明；**M5 沿用，不要顺手改回去**。
- **K9 数据契约与错误码**：`csvio.ERROR_CODES` 单点定义（7 个）+ 文档表互等门；行号 = 物理行号；一次报全部错误；缺失标记 → `None`（不补 0 不插值）。
- **K10 编码守卫**：`cli.py` 是 `_ensure_utf8_stdio()` 的单点定义，`tools/` 下每个可执行入口导入并调用它（**新增脚本必须补挂**）；子进程读写显式 `encoding=`；CI env `PYTHONUTF8=1`。
- **K11 生成器纪律**：splitmix64 自研 RNG；seed 显式传参并写 manifest；`--check` 两层断言；真值只存输入与期望、禁 `observed`。
- **K12 零外链**：`render` 出口常驻 `assert_no_external_resources(html)`；**HTML 加载时不得发起任何网络请求**（浏览器实测 `performance` 资源条目 0）。`<svg>` 不能带 `xmlns="http://..."`，也不能用 `href=`/`xlink:href`/`<use>`/`clip-path: url(#id)`；`url()` 只放行 `data:`。
- **K13 复算指纹一致性**：`canonical_json_bytes`/`quantize`/`fixed_to_str`/`sha256_hex`/`canonical_digest` 是**唯一**实现；JS 镜像必须逐字节产出同一份规范 JSON；未通过 Node 对账的 HTML 不构成交付物。
- **K14 数字白名单（M5 落地）**：报告数字必须命中 `facts.json`；**未命中列出全部**（不是首条）并 exit 1；`render --narrative` 在构造期跑同一门禁，未通过**零产物**。台账 `fact_id` 唯一（重复即报错），`catalog`（episode_ids / series_ids / detectors / archive_rows）是 episode 引用与行号门的**唯一解析来源**（所以缺 `catalog` 的账本是 exit 2 的用法错误）。
- **K15 不留桩（D14）**：未落地模块不产桩；`tests/test_skeleton.py::TestNoSentinelStubs` 常驻扫描 `src/`+`tools/` 的 `.py`/`.js`（含正向对照与变异）；**注释也会被扫**（别写 `placeholder` / `NotImplementedError` / `TODO: 实现`）。
- **K16 命令注册表三处同步**：`cli.COMMANDS` / `cli.STAGE_NOT_READY`（**M5 后为空，别再往里面加**）/ 测试侧 `_ARGS_BY_COMMAND` + `_INPUT_FILES`。
- **K17 冻结数据的已知形状**：长表按 (时间, series) 交错；温度行含 1 个重复时间戳；四种时间戳表示成块交替；缺失写成空串、零值写成 `0.00`；每 series 各有 1 处时间缺口；humidity 噪声幅度 200 milli；3 个 series 各 985/987/988 行；1 小时的 `heat_bin_ms` 得 **84 箱**；默认 spec 全量 **178 episodes / 653 detections**。
- **K18 指纹黄金值与探针方向**：异常集指纹 `6020a3d3…` 钉在 `selftest.GOLDEN_ANOMALY_DIGEST`、`tests/test_detect.py`、`tests/test_mirror.py`、`tests/test_render.py` 多处；任何检测算术或数据改动都会让它变红——**故意的跳线**。呈现参数与 M5 的台账都刻意不碰它。探针必须**增加**一项无法满足的要求（删段只会让要求一起消失）。
- **K19 "39 段"不是"39 个 episode"**：探针两侧的"25 分钟"三对必须合并；对账判据是**覆盖**而非数量相等。
- **K20 嵌入契约四条铁律**：① 内联样本是十进制文本（`repr` 最短往返串）；② 三块 `<script id>` = `zaa-payload`/`zaa-mirror`/`zaa-boot`，**块体前后不加换行**；③ **产物里不得出现任何 `$`**（`--narrative` 里带 `$` 在 CLI 层就 exit 2）；④ `verify` 与 `tools/mirror_parity.py` **共用 `mirror.verify_artifact`**。
- **K21 红必须能指认自己**：篡改探活要求"必变红 **且**首个差异点落在被篡改的 series"，否则 exit 1。**指纹相等不是定点规则的正确性证据**（改半偶边界在冻结指纹上实测仍全绿），定点规则另有跨语言向量门（`mirror.FIXED_POINT_VECTORS`）。
- **K22 Node 前提**：Node 缺失 → exit 4 + 两条补救路径，不静默跳过；产物不合契约 → exit 2；镜像跑不起来 → exit 1。
- **K23（M4）呈现与判定分家**：`render --spec` 是"检测 run-spec + 可选的 `"render"` 块"，未知检测键与未知呈现键都是 exit 2。
- **K24（M4）几何全整数 + 纹理是结构**：`layout` 的所有返回值里**没有浮点数**；行号 → 像素 = `left + index * plot_width // (n-1)`；三类异常区用三种结构（斜纹线段 / 竖栅 / 虚线框），不靠色深；时间缺口按缺席样本数就地加宽（映射不动）。
- **K25（M4）产物出口两条断言**：`assert_no_external_resources` + `assert_no_template_slots`，都在 `build_view_html` 的出口常驻。M3 的教训是"Node 通道绿 ≠ 人读那一面成立"，所以这两条必须能被**注入式**测试证伪。
- **K26（M4）滑杆只改显示**：滑杆重算必须走产物内联的同一份 JS 内核；**基线下复算必须等于构建指纹**；滑杆结论与构建指纹**分块显示**、互不覆盖；滑杆值渲染成 run-spec 片段。M5 的报告区横幅与它分块并存（浏览器实测两者同时在页面上且互不覆盖）。
- **K27（M4）页面固定浅色**：`:root { color-scheme: light }` 有测试钉住（打印是目标形态）。
- **K28（M5 新增）门禁在构造期，不在调用方**：白名单跑在 `build_view_html` 里（`raise report.NarrativeRejected`），不是跑在 `cmd_render` 里——否则 `write_view` / 直接调用 `build_view_html` 的路径会绕过它。新增任何"把叙事写进产物"的入口都要走同一个构造器。
- **K29（M5 新增）掩码 + 四类各自成门**：抽取数字前先把 ISO 时间戳、`CSV 行 N`/`文件行 N`、episode 引用、`row N`/`行 N`/`第 N 行` 用**等长空白**挖掉（偏移量不变，上下文仍能给出）；四类各有自己的门。**掩码长度必须与原串相同**，否则报错里的偏移量会指错位置。
- **K30（M5 新增）中文数字必须带量词**：`零一二三四五六七八九十百千万两` + 量词（处/个/段/条/次/点/列/种/类/组/对/张/块/格/箱/倍/分钟/小时/毫秒/秒/天/月/年）才算数字；`统一`/`一般`/`十分` 不计入。这是**有意的假阳性妥协**（无此限制门禁会在第一次使用后被关掉），代价写在 `plan/自评表.md` 第五节。
- **K31（M5 新增）白名单是值级门禁**：命中 = "值相等"，不是"用得对"。一个恰好等于某条事实的编造数字能过；要判断用法是否得当，读 Episode 卡片与质量卡。这条同时写在 README「已知环境问题」与 `SKILL.md` 的诚实边界里——**别在发布文案里把它说成"数字不可能错"**。
- **K32（M5 新增）`selftest.CHECKS` 的条数有两处硬编码**：`selftest.py` 的元组与 `tests/test_selftest.py::test_every_check_is_registered_with_a_probe` 的字面量（现为 6）。改检查数必须两处同改。

## 4. 本机环境坑（只写实测过的）

- 用 `py` 不是 `python`；一律 `py -X utf8`。本机 **3.8.8 与 3.12.10** 两条通道；每棒双解释器全量跑。`python` 是微软商店占位符（直接跑会以 exit 49 失败）。
- 全程 `PYTHONDONTWRITEBYTECODE=1`；源模式跑测：`PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 py -3.12 -X utf8 -m pytest tests/ -q`。
- 全量套件时长（本轮实测）：3.12 127.5 s / 3.8 145.5 s / 干净 venv 62.4 s。**差异主要是机器负载与 .pyc 缓存策略**（venv 跑没设 `PYTHONDONTWRITEBYTECODE`），别把单次时长当跨版本证据。
- pip 装包必须 `NO_PROXY="*" no_proxy="*"` + 清华镜像；`py -3.12 -m venv .venv-verify` + `pip install -e ".[dev]"` 一次成功；**验证用 venv 用完立刻删**。
- **`py -3.12 -m venv` 里没有 setuptools**：想在本机打 wheel 必须先 `pip install setuptools wheel`。
- Git Bash 的 `/tmp` 与 Windows 原生 Python 不通：临时文件用仓库内相对目录（`.tmp/`，已 gitignore）。
- **本机有 Node v24.15.0**；`verify` 的 Node 缺失分支用 `--node <不存在的名字>` 确定性触发。
- **editable 安装的 `_PACKAGE_ROOT` 仍指向仓库根**（src 布局三层 dirname），所以命令行**无法**在源码库内触发 `selftest` 的 exit 4；本轮冒烟用"把 `src/anomaly_atlas` 拷到 `.tmp/pkg/` + cwd 设为系统临时目录"来真跑这条路径。
- **`pytest` 的 `capsys` 是 function-scoped**：不要塞进 module-scoped fixture（会 `ScopeMismatch`）。
- **测试提速**：载体重建一次约 1.9 s（解析 + 一次全量检测 + 渲染），所以 `test_render.py`/`test_mirror.py`/`test_facts.py`/`test_report.py` 的 module fixture 都用 `detect.detect_all_detailed` 把**同一趟**的 detections 直接交给调用方；台账构建再花 ~1 s（`density_bins` 扫 2960 行）。
- **哨兵扫描器连注释一起扫**：命中 `placeholder` / `NotImplementedError` / `TODO: 实现` 即红。
- **变异脚本必须三连断言**（替换前 marker 唯一 → 替换后字节已变 → 还原后字节一致），且**要挑对靶子**。本轮第二批实测教训（新增）：**断言要能失败**——"违规 token 里不含某 fact_id"永远成立，等于没断言；**靶子要挑到能区分的类上**——"编造即拒绝"那一类对若干变异是绿的，真正能区分的是"真引用必须通过"那一类。
- **K4 的 AST 门覆盖整个 `src/` 包，包括 `selftest.py`**：在 selftest 里写 `10 ** d` 会让 `test_no_transcendental.py` 变红（本轮实测）。用 `facts.scaled_value` 之类的整数标尺函数代替。
- **浏览器通道**：ZCode 内置浏览器（IAB 后端）**不支持 `file:` 导航**（`goto()` 只接受 http/https/about:blank）。验产物用本地回环：`py -3.12 -m http.server 8731 --bind 127.0.0.1` → 开 `http://127.0.0.1:8731/examples/atlas.html`；**验证完按 PID 杀掉**（`netstat -ano | grep :8731` → `taskkill //F //PID <pid>`）。截图通道分辨率不足以判读 1 px 线宽，"图上有墨"要用 **DOM 几何证据**；计算样式与打印规则从 **CSSOM** 读；零请求用 `performance.getEntriesByType("resource").length` + 本地服务访问日志双向核对（本轮日志实测：每次导航只有一次文档 GET）。
- **IAB 的 tab id 形如 `iab-tab:<uuid>`**，每轮 JS 调用都是新内核——必须先 `tabs.list()` 拿事实，再 `tabs.get(id)`，不要凭记忆复用 id（本轮就吃到一次 `Browser tab 'iab-1' is unavailable`）。

## 5. DoD 逐项 checklist（M6 出口）

- [ ] 建仓（public，账号 `yuluo554`）+ 首推，**CI 四矩阵首推全绿**
- [ ] 每个 push/tag 事件恰一次 CI run 且 `head_sha` 全对上的对账表
- [ ] `git tag`（版本号与 `pyproject.toml`/`VERSION` 一致）+ GitHub Release（附 HTML 产物 + 基准数据）
- [ ] `plan/RELEASE-M6.md` 三件套留档（tag / Release URL / 产物 sha256 / CI 对账表）
- [ ] **发布物本体已验**：下载 Release 附件 → `verify` exit 0 / VERIFIED；附件 sha256 与本地一致；clone 后新目录 `selftest` 全绿
- [ ] `plan/00·02·05·06` 状态回写（M6 行）并 commit
- [ ] 发布后**冻结资产零改动**（`data/`、`examples/atlas.html`、`tests/` 快照）

## 6. 关键命令速查

```bash
cd <repo>
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1

py -3.12 -X utf8 -m pytest tests/ -q          # 全量测试（3.8 同；约 128 s / 146 s）
py -3.12 -X utf8 -m pytest tests/test_facts.py tests/test_report.py -q

# 检测（现在落 4 个文件，含 facts.json）
py -3.12 -X utf8 -m anomaly_atlas.cli detect data/synthetic/series.csv --out-dir out
cat out/anomaly_set.sha256                     # 6020a3d3…
py -3.12 -X utf8 -m anomaly_atlas.cli selftest # 6 检查 + 6 探针，全绿 → exit 0

# M5 报告门禁（干净 → 0；编造 → 1 且逐条列出）
printf '全档案共 178 段 Episode、653 个异常点。\n' > report.md
py -3.12 -X utf8 -m anomaly_atlas.cli check-report --facts out/facts.json --text report.md
printf '共 987654321 段异常。\n' > fabricated.md
py -3.12 -X utf8 -m anomaly_atlas.cli check-report --facts out/facts.json --text fabricated.md
py -3.12 -X utf8 -m anomaly_atlas.cli render data/synthetic/series.csv -o atlas.html --narrative report.md

# M4 标注图（产物替换后用同一条命令重建，与仓库产物逐字节相同）
py -3.12 -X utf8 -m anomaly_atlas.cli render data/synthetic/series.csv -o examples/atlas.html

# M3 复算门禁（本机有 Node）
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html      # VERIFIED, exit 0
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html --tamper-index 3   # MISMATCH + 定位, exit 1
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html --node no-such-node # exit 4 + 两条补救路径

# 浏览器人读面（IAB 不支持 file:，走本地回环；验完按 PID 杀掉）
py -3.12 -X utf8 -m http.server 8731 --bind 127.0.0.1 &
#   开 http://127.0.0.1:8731/examples/atlas.html
netstat -ano | grep :8731        # 找 PID
taskkill //F //PID <pid>

# 安装跑法（本机实测一次成功；验证完删 venv）
py -3.12 -m venv .venv-verify
NO_PROXY="*" no_proxy="*" ./.venv-verify/Scripts/python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv-verify/Scripts/python.exe -m pytest -q
./.venv-verify/Scripts/anomaly-atlas.exe verify examples/atlas.html
rm -rf .venv-verify

# 发布（M6）
gh repo create 10-17-timeseries-anomaly-atlas --public --source . --remote origin
git push -u origin main
gh run list --limit 20          # 与 push 事件逐条对账
gh release create v0.1.0 examples/atlas.html data/synthetic/series.csv \
  data/synthetic/manifest.json data/truth/truth.json data/truth/hash.txt
```
