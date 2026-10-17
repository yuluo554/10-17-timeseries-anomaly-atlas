# HANDOFF-M4（M3 已收尾 → 下一棒 M4 单文件标注图）

> 用法：新对话 `/goal 读取 <项目绝对路径>\plan\HANDOFF-M4.md 继续完成任务`（库内一律相对路径）。

## 1. 当前进度 + 证据

- **M3 浏览器复算硬门禁已完成**。今天有真实行为的模块：M1/M2 的全部（`cli`/`timebase`/`csvio`/`profile`/`canon`/`detect`/`episodes`/`selftest`）+ M3 的 **`mirror/zaa_mirror.js`**（约 1450 行手写 JS 镜像：4 类检测器 / Episode 语义 / 规范 JSON / 自实现 SHA-256 与 UTF-8）、**`mirror.py`**（产物契约读取 + Node 对账 + `verify`）、**`render.py`**（嵌入契约 + M3 最小载体页 + 零外链常驻断言）、**`tools/mirror_parity.py`**（`--html` 验 + `--build` 造载体页）。仍为 **docstring-only**：`layout`/`facts`/`report`（不产桩，D14）。
- **`STAGE_NOT_READY` 现余两键** `{render:M4, check-report:M5}`；`verify` 已整项退役（常量 → CLI 接线 → 测试 → 文档 → 决策记录五处同步，见 `plan/06` D21 与 §5 checklist）。
- **证据（本轮实测）**：
  - 三处全绿：`py -3.12` 85.4 s / `py -3.8` 59.7 s / 干净 venv（3.12 + `pip install -e ".[dev]"`）46.5 s，各 **474 passed, 4 skipped**（4 skip = `render`/`check-report` 的 not-ready 用例按设计退役）。
  - **逐位一致**：`examples/atlas.html` 里那份镜像在 Node 下重算出的规范 JSON 与 sha256 与构建值**逐字节相等**（`6020a3d3…`，178 episodes / 653 detections / 2960 内联样本）；`verify` → exit 0 打印 VERIFIED。
  - **篡改必红且定位**：`--tamper-index 3 / 1500 / 2900`（三个 series 各一）逐条实测 → MISMATCH + 首个差异点报出 `series_id / detector / 点序号 / 期望 / 实算 / 源行号`，exit 1。`3` 那条的首个差异点正是被篡改的那一行（`energy_kwh` row 13：`rules.cusum` 首点由 row 67 变 row 13）。探针"没变红"或"红了指不到那个 series"都按**探针失败** exit 1。
  - **向量双侧断言**：SHA-256（空串 / `abc` / 55 / 56 / 64 / 65 / 96 B / 多字节 UTF-8）由 Python `hashlib`+`canon.sha256_hex` 与**产物自带镜像**的 Node 侧共用同一份 `mirror.SHA256_VECTORS`；另有一组**定点向量** `mirror.FIXED_POINT_VECTORS`（半偶舍入并列 + 负值 + 6 位定点串）跨语言对账。
  - **变异验证 14/14 变红**（每条指名变红的测试；三连断言：marker 唯一 → 字节已变 → 还原一致）。其中 **1 条最初仍绿**：把镜像半偶边界 `frac > 0.5` 改成 `frac > 0.4999995`，冻结数据的指纹对账**照样全绿**（没有分数落进那 5e-7 宽的口子）→ 补了定点向量门后才变红。另 1 条是**我的变异目标选错了**（把 `verify` 推回 exit 3，`test_skeleton` 的 not-ready 用例反而变绿，因为"在注册表里就答 3"是它的契约）→ 改指 `test_the_cli_verifies_and_exits_zero` 才红；记在这里因为它是"变异验证本身要挑对靶子"的实例。
  - 退出码冒烟 **29 条逐条实测**（0/1/2/3/4 全五档）：含 `verify` 非产物 → 2、篡改越界 → 2、`--node` 不存在 → 4 **且打印两条补救路径**、`mirror_parity` 无参数 → 2、`--build` 缺 CSV → 2；失败路径**零副作用**（29 条前后全仓文件快照差集为空）。
  - **安装面**：干净 venv 的裸 console script `anomaly-atlas verify examples/atlas.html` → 0、`selftest` 五项全绿；另建 wheel 实测 `anomaly_atlas/mirror/zaa_mirror.js` 在包内（`[tool.setuptools.package-data]`），并把 wheel 装进**第二个一次性 venv** → `verify` 通过且**重建的载体页与仓库内 `examples/atlas.html` 逐字节相同**（447397 B）；验证完两个 venv 与 wheel 目录立即删除。
  - **节点环境更正**：本机**有 Node**（`v24.15.0`）——M1/M2 记录里的"本机没有 Node"已过期；`mirror_parity` 在本机是真跑，不再是"只能走 exit 4 分支"。
- **诚实口径**：**未接远端，CI 待首推验证**。CI 已补五步 M3 冒烟（Node 在位断言 + 载体页构建 + `verify` 正常产物 + 篡改必红且定位 + Node 缺失必须 exit 4 + `mirror_parity` 复验），**均未实跑**；ubuntu/windows 腿与 CI 步骤形态仍属本地等价校验缺口。

## 2. 下一棒待办（M4 单文件标注图）

1. **`layout.py`（确定性坐标与分箱）**：主序列视图 y 轴取全序列 min/max（含异常带 padding）；x = **行号 → 像素的固定线性映射**，坐标**取整到整数像素**；缺口 / 零值 / 缺失段的分箱边界由固定规则算出，三类必须互相可区分（**缺口 = 显式纹理 pattern，不靠颜色深浅**，P5）；Episode 放大窗口 = `[start_row − pad, end_row + pad]`（`pad` 进 run-spec）；密度热条按固定时间分箱（`heat_bin_ms` 进 run-spec），覆盖度用**整数比率的定点点数**。small multiples 共享同一行号→像素规则。
2. **`render.py` 复用 M3 嵌入契约做完整标注图**（`render_html`）：主序列 + 异常区间带 + 峰值标记 + 缺口纹理 / Episode 卡片（局部放大 + 阈值线**由该 Episode 的 `threshold_ref` 派生** + 检测器 + 得分 + 源行号 + `episode_id`）/ 多指标 small multiples / 异常密度热条 / 阈值灵敏度滑杆 / 数据质量卡 / 报告区 / VERIFIED-MISMATCH 徽章 / 打印样式（黑白可辨，卡片不截断）。
   - **滑杆只改显示不改判定**（反模式 3 的例外通道）：`k_scale`（对三个滚动类检测器阈值同乘比例，1.0 基线）+ `max_gap_ms` 两档，重算**必须走同一份 JS 内核**。`ZAA.recompute(payload)` 读的就是 `payload.run.params`，所以滑杆的天然实现是**改 payload 里那份 run-spec 再重跑同一个 `recompute`**（`k` 等十进制参数在落盘形态里是 6 位定点串，改的时候要按同一形态写）；**内嵌的构建指纹是不可变的那一份**，滑杆结果必须显式标注为"当前 run-spec 的复算"，不得覆盖徽章结论。滑杆值同步渲染成 run-spec JSON 片段。
   - `build_id` 用内容派生（规范 JSON sha256 前 16 位），**不得是时间戳**（K2 禁时钟字段）。
3. **`render` 落地 → K1 退役第三步**（同一提交内五处同步）：`STAGE_NOT_READY` 删 `render` 键 → CLI 接线（已预置）→ 测试（`test_skeleton.py` 注册表不变、not-ready 用例自动 skip，现余 `check-report` 一条）→ README 与 `plan/00·02·03·05` 状态表 → 决策记录补一条；**CI 同提交补 `render` 离线冒烟**（产物零外链 + 双跑逐字节）。
4. **产物替换的同步项（重要，不同步就会红）**：`examples/atlas.html` 从"最小载体页"换成完整标注图后，必须同步改
   - `tests/test_render.py::TestCarrierIsDeterministic::test_the_committed_artifact_is_the_builder_output`（钉的是"仓库产物 == 构建器输出"），
   - `tests/test_render.py::TestCarrierShape::test_the_page_states_what_it_is`（钉 `render.CARRIER_TITLE` 与 "M4" 字样），
   - `plan/02` 的目录树注记与 README 结构表里"examples/atlas.html = M3 最小载体页"的措辞。
   嵌入契约（`zaa-payload` / `zaa-mirror` / `zaa-boot` 三个 id、块体不加换行、payload 无浮点字面量）**保持不变**——`verify` 与 `tools/mirror_parity.py` 依赖它，改了要一起改 `mirror.py` 的常量与 `tests/test_mirror.py`。
5. **零外链常驻 + 双跑逐字节 + 几何一致 + 打印黑白可辨**：`assert_no_external_resources` 继续在出口常驻（现有实现已放行 `url(data:…)`，纹理 pattern 可用内联 data URI）；同输入两跑产物逐字节相同；同一输入两次渲染的几何数值一致（坐标取整后无浮点漂移）。
6. **收尾**：DoD 验证（双解释器 + 干净 venv + **变异验证**，靶子要挑对：改分箱边界 / 改像素映射 / 去掉零外链断言 / 让滑杆越过 JS 内核自己算）→ `plan/00·02·03·05·06` 状态回写 → 写 `plan/HANDOFF-M5.md` → 删除临时目录与 venv → commit。

## 3. 既定口径清单（K，动了会打挂测试）

- **K1 退出码契约（D8）**：0 成功 / 1 门禁或自检发现缺陷 / 2 用法与输入错误 / 3 阶段未就绪 / 4 环境前提不满足。`STAGE_NOT_READY` 现为 **`{render:M4, check-report:M5}`**；落地一个键**整项退役**、五处同步（常量 → CLI 接线 → 测试 → 文档 → 决策记录）；空后删除 `EXIT_NOT_READY` 常量。
- **K2 序列化冻结**：JSON 落盘统一走 `canon.canonical_json_bytes`（`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行）；**产物里禁时钟字段**；`profile.json`/`run.json` 里没有任何 ISO 串（ISO 只出现在 `anomalies.json` 的 Episode `start`/`end`）。
- **K3 规范 JSON 只含整数与字符串**：`canon.assert_hashable` 在落盘出口拒浮点；`quantize` 半偶舍入（默认 6 位）、`fixed_to_str` 由整数构造十进制串；十进制的检测器参数以 6 位定点串落 `run.json`。**M3 补充**：内联样本也走这条规则（见 K20）。
- **K4 数值可镜像**：哈希/判定路径只允许 `+ - * / floor ceil abs min max` 与比较；幂次展开为连乘；**禁一切超越函数与库归约函数**。门在 `tests/test_no_transcendental.py`：AST（py）+ 词法（js）+ 豁免表 + 变异。**镜像文件在扫描范围内**（有测试钉住这一点——挪文件就会红）。Python 与 JS 的 `%` / `//` 语义差异：相位与整除只允许**非负操作数**。
- **K5 时间口径**：UTC **整数 epoch 毫秒**；落盘 ISO 定点串由整数反算；小数秒**截断**不四舍五入。镜像**不重实现时间解析**（内联的已是整数毫秒）。
- **K6 排序与 tie-break**：所有排序给**全序比较器**（含源行号 index tie-break）；Episode 严重度键 = `peak_score_q` 降 → `duration_ms` 降 → `start_row` 升 → `detector` 字典序；`episode_id = "<series_id>-E<NNN>"`（按 series 计数）。
- **K7 Episode 合并**：时间域 `max_gap_ms`；相邻异常点时间差 **≤** 该值即合并；**按 `(series_id, detector)` 分组**；与剖面的"缺口区间"是两个概念。
- **K8 参数面与生效值**：`run.json` 记录**解析后的最终值**（含估出的 `period_points`、`period_reject_*`、`max_gap_ms`、`quant_decimals`、版本号）；复算侧消费生效值、**不重跑估计**；引擎里不留隐形默认（逐字 golden 断言）；**生效参数块在异常集指纹里**。
- **K9 数据契约与错误码**：`csvio.ERROR_CODES` 单点定义（7 个）+ 文档表互等门；行号 = 物理行号；一次报全部错误；缺失标记 → `None`（**不补 0 不插值**）。
- **K10 编码守卫**：`cli.py` 是 `_ensure_utf8_stdio()` 的单点定义，`tools/` 下每个可执行入口导入并调用它（**新增脚本必须补挂**）；子进程读写显式 `encoding=`；CI env `PYTHONUTF8=1`。
- **K11 生成器纪律**：splitmix64 自研 RNG；seed 显式传参并写 manifest；`--check` 两层断言；真值只存输入与期望、禁 `observed`；生成器断言真值非平凡**且可检出**（幅度下限 ≥ 8× 噪声幅度、日周期摆幅 ≥ 3× 噪声幅度）。
- **K12 零外链**：`render` 出口常驻 `assert_no_external_resources(html)`；M3 的最小载体页与 M4 的完整图都必须零外链。**HTML 加载时不得发起任何网络请求**。现有实现：先屏蔽脚本体再扫标记（`http(s)://` / `src=` / `href=` / `<link>` / `<iframe>` / `@import` / 协议相对 `//`），同时扫脚本体里的网络 API（`fetch` / `XMLHttpRequest` / `WebSocket` / `EventSource` / `importScripts` / `sendBeacon`），`url()` 只放行 `data:`。
- **K13 复算指纹一致性**：`canonical_json_bytes`/`quantize`/`fixed_to_str`/`sha256_hex`/`canonical_digest` 是**唯一**实现；JS 镜像必须逐字节产出同一份规范 JSON。**M3 的硬门禁已落地**：未通过 Node 对账的 HTML 不构成交付物（`verify` / `tools/mirror_parity.py` exit 0 才算）。
- **K14 数字白名单**：报告数字必须命中 `facts.json`（M5）。
- **K15 不留桩（D14）**：未落地模块**不产** `NotImplementedError`/`pass`/`return 0` 桩；`tests/test_skeleton.py::TestNoSentinelStubs` 常驻扫描 `src/`+`tools/`（含正向对照与变异）。**新增 JS 文件也在扫描范围内**（`zaa_mirror.js` 已被扫到，它有真实行为所以是干净的）。
- **K16 命令注册表三处同步**：`cli.COMMANDS` / `cli.STAGE_NOT_READY` / 测试侧 `_ARGS_BY_COMMAND` + `_INPUT_FILES`。
- **K17 冻结数据的已知形状**（post-D19）：长表按 (时间, series) 交错（同一 series 相邻行号差 3）；温度行含 1 个重复时间戳；四种时间戳表示成块交替；缺失写成空串、零值写成 `0.00`；每 series 各有 1 处时间缺口；humidity 噪声幅度 200 milli。
- **K18 指纹黄金值与探针方向**：异常集指纹 `6020a3d3…` 钉在 `selftest.GOLDEN_ANOMALY_DIGEST`、`tests/test_detect.py`、`tests/test_mirror.py`、`tests/test_render.py` 多处；**任何**检测算术或数据改动都会让它变红——这是**故意的跳线**。探针必须**增加**一项无法满足的要求（删段只会让要求一起消失）。
- **K19 "39 段"不是"39 个 episode"**：探针两侧的"25 分钟"三对必须合并；对账判据是**覆盖**而非数量相等。当前默认 spec 全量输出 178 episodes / 653 detections（7 条检测器流）。
- **K20（M3 新增）嵌入契约三条铁律**：① **内联样本是十进制文本**（`repr` 最短往返串；镜像用 `parseFloat` 最近双精度还原），所以整份 payload 仍可过 `canon.assert_hashable`——**别改成内联浮点字面量**；② 三块 `<script id>` = `zaa-payload`/`zaa-mirror`/`zaa-boot`，**块体前后不加换行**，因此"产物里那段镜像源码"与 `zaa_mirror.js` **逐字节相等**（有测试钉住）；③ `verify` 与 `tools/mirror_parity.py` **共用 `mirror.verify_artifact`**——不要另写一份判定。
- **K21（M3 新增）红必须能指认自己**：篡改探活打**内联数据**（series 存储序 + 行序，位移量 = 该 series 跨度 ×1000，常数序列回退 10^6），要求"必变红 **且**首个差异点落在被篡改的 series"；探针不变红或红了指不到那个 series → **exit 1**（探针失败）。**指纹相等不是定点规则的正确性证据**：改半偶边界在冻结指纹上实测仍全绿，故定点规则另有跨语言向量门（`mirror.FIXED_POINT_VECTORS`）；M4 若新增任何哈希路径算术，按同一思路补向量而不是指望数据集踩到边界。
- **K22（M3 新增）Node 前提**：Node 缺失 → **exit 4** + 两条补救路径（装 Node / 走浏览器徽章），不静默跳过；产物不合契约 → exit 2；镜像跑不起来 → exit 1。本机**有** Node（v24.15.0）；CI 的 windows/ubuntu runner 也预装（CI 第一步显式 `node --version` 断言，避免"门禁静默降级成没得验"）。JS 镜像随包分发（`[tool.setuptools.package-data]`），wheel 内含。

## 4. 本机环境坑（只写实测过的）

- 用 `py` 不是 `python`；一律 `py -X utf8`。本机 **3.8.8 与 3.12.10** 两条通道；每棒双解释器全量跑。
- 全程 `PYTHONDONTWRITEBYTECODE=1`；源模式跑测：`PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/ -q`。
- 全量套件时长（本轮实测）：3.12 85.4 s / 3.8 59.7 s / 干净 venv 46.5 s（三者差异主要来自 Node 子进程与载荷构建，别把单次时长当作跨版本证据）。
- pip 装包必须 `NO_PROXY="*" no_proxy="*"` + 清华镜像；`py -3.12 -m venv .venv-verify` + `pip install -e ".[dev]"` 一次成功；**验证用 venv 用完立刻删**。
- **`py -3.12 -m venv` 里没有 setuptools**：想在本机打 wheel 必须先 `pip install setuptools wheel`（否则 `pip wheel --no-build-isolation` 报 `BackendUnavailable: Cannot import 'setuptools.build_meta'`）。打轮实测命令：`python -m pip wheel . --no-deps --no-build-isolation -w .tmp/wheel`，再用第二个 venv `pip install --no-deps --no-index .tmp/wheel/*.whl`。
- Git Bash 的 `/tmp` 与 Windows 原生 Python 不通：临时文件用仓库内相对目录（`.tmp/`，已 gitignore）。
- **本机有 Node v24.15.0**（M1/M2 记录的"本机没有 Node"已过期）。`verify` 的 Node 缺失分支用 `--node <不存在的名字>` **确定性**触发，不依赖机器状态。
- **`pytest` 的 `capsys` 是 function-scoped**：不要塞进 module-scoped fixture（会 `ScopeMismatch`）。
- **测试提速**：载体重建一次约 2.7 s（一次全量检测），所以 `test_render.py` 的 module fixture 用 `detect.detect_all_detailed` 把**同一趟**的 detections 直接交给 `build_carrier_html(..., detections)`——重跑检测器会让每个用例多花 2.7 s（本条是实测优化：该文件从 30 s 降到 5.9 s）。
- **变异脚本必须三连断言**（替换前 marker 唯一 → 替换后字节已变 → 还原后字节一致），且**要挑对靶子**：本轮就有一条把 `verify` 推回 exit 3 的变异在 `test_skeleton` 的 not-ready 用例上**变绿**（"在注册表里答 3"正是该测试的契约），改指 `test_the_cli_verifies_and_exits_zero` 才变红。第二种假绿：断言从"被测产物自身"读回期望值——**写断言优先用字面量 pin 住契约**。
- **AST 细节**：`ast.Pow` 是算符节点、没有 `lineno`，要检测 `**` 必须看 `ast.BinOp(op=Pow)` 与 `ast.AugAssign(op=Pow)`；`ast.Name` 扫名字会误报局部变量，只扫**调用**与**属性**。
- **JS 词法门对注释同样敏感**：镜像里连注释都不能出现 `**` / `Math.exp(` 之类的字面写法（`test_no_transcendental` 是逐行正则）。同理，脚本体里若出现 `file://` 这样的 scheme，会让"零外链"的朴素扫描难做——M3 的做法是先屏蔽脚本体再扫标记，注释里也顺手避开了 scheme 写法。

## 5. DoD 逐项 checklist（M4 出口）

- [ ] `layout.py`：坐标取整到整数像素；y 轴含异常带 padding；缺口/零值/缺失分箱固定且**互相可区分（缺口用纹理 pattern）**；Episode 放大窗口与 `heat_bin_ms`/`pad` 进 run-spec
- [ ] `render.py` 完整标注图（复用 M3 嵌入契约，三个块 id 与"块体不加换行"不变）：主序列/异常带/峰值/缺口纹理 + Episode 卡片（阈值线取自 `threshold_ref`）+ small multiples + 密度热条 + 灵敏度滑杆（走同一 JS 内核，值渲染成 run-spec 片段）+ 质量卡 + 报告区 + VERIFIED/MISMATCH 徽章 + 打印样式（黑白可辨）
- [ ] 零外链断言常驻出口；双跑逐字节；同输入几何一致；断网可开
- [ ] `render` 从 `STAGE_NOT_READY` 删除并接线真实现，五处同步完成；CI 同提交补 `render` 离线冒烟
- [ ] 产物替换同步项（见待办 4）逐条改到，`verify` / `mirror_parity` 在新产物上仍 exit 0
- [ ] 三处全绿（3.8 / 3.12 / 干净 venv）+ 退出码冒烟逐条实测（含零副作用）+ **变异验证（靶子挑对）**
- [ ] `plan/00·02·03·05·06` 状态回写 + `plan/HANDOFF-M5.md` 六节齐落盘并 commit
- [ ] CI 首推全绿 —— **未接远端，待 M6 首推验证**（不可本机实跑；ubuntu/windows 腿与 CI 步骤形态是本地等价校验的缺口）

## 6. 关键命令速查

```bash
cd <repo>
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1

py -3.12 -X utf8 -m pytest tests/ -q          # 全量测试（3.8 同；约 85 s / 60 s）
py -3.12 -X utf8 -m pytest tests/test_mirror.py tests/test_render.py -q

py -3.12 -X utf8 -m anomaly_atlas.cli detect data/synthetic/series.csv --out-dir out
cat out/anomaly_set.sha256                     # 6020a3d3…
py -3.12 -X utf8 -m anomaly_atlas.cli selftest # 5 检查 + 5 探针，全绿 → exit 0

# M3 复算门禁（本机有 Node）
py -3.12 -X utf8 tools/mirror_parity.py --build examples/atlas.html   # 造 M3 最小载体页
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html      # VERIFIED, exit 0
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html --tamper-index 3   # MISMATCH + 定位, exit 1
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html --node no-such-node # exit 4 + 两条补救路径
py -3.12 -X utf8 tools/mirror_parity.py --html examples/atlas.html    # 同一判定的工具入口

# 安装跑法（本机实测一次成功；验证完删 venv）
py -3.12 -m venv .venv-verify
NO_PROXY="*" no_proxy="*" ./.venv-verify/Scripts/python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv-verify/Scripts/python.exe -m pytest -q
./.venv-verify/Scripts/anomaly-atlas.exe verify examples/atlas.html
# 想在本机打 wheel：先 pip install setuptools wheel，再
#   ./.venv-verify/Scripts/python.exe -m pip wheel . --no-deps --no-build-isolation -w .tmp/wheel
```
