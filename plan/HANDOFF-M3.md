# HANDOFF-M3（M2 已收尾 → 下一棒 M3 浏览器复算硬门禁）

> 用法：新对话 `/goal 读取 <项目绝对路径>\plan\HANDOFF-M3.md 继续完成任务`（库内一律相对路径）。

## 1. 当前进度 + 证据

- **M2 检测内核已完成**。今天有真实行为的模块：`cli.py`、`timebase.py`、`csvio.py`、`profile.py`、`canon.py`（M1 原语 + M2 的 `build_anomaly_set`/`canonical_digest`/`CANON_VERSION`）、`detect.py`（**4 类检测器 + 稳妥周期估计 + `cmd_detect`**）、`episodes.py`（**合并/严重度排序/`episode_id`**）、`selftest.py`（**五项检查各带可证伪探针**）、`tools/gen_synthetic_series.py`。仍为 **docstring-only**：`layout`/`render`/`facts`/`report`/`mirror`（不产桩，D14）。
- **`STAGE_NOT_READY` 现余三键** `{verify:M3, render:M4, check-report:M5}`；`detect`/`selftest` 已整项退役（常量 → CLI 接线 → 测试 → 文档 → 决策记录五处同步）。
- **证据（本轮实测）**：
  - 三处全绿：`py -3.8` 44.4 s / `py -3.12` 34.1 s / 干净 venv（3.12 + `pip install -e ".[dev]"`）47.5 s，各 **411 passed, 3 skipped**（3 skip = `render`/`verify`/`check-report` 的 not-ready 用例按设计退役）；venv 产出的 `anomalies.json` 与 `run.json` 与源码直跑 **`cmp` 逐字节相同**；验证完 venv 已删、`git status` 只余本棒该提交的文件。
  - **真值全段对账 39/39**（逐段非抽样；`spike` 22 / `level_shift` 5 / `variance_shift` 6 / `missing_run` 3 / `zero_run` 3）；**6/6 合并探针**在 `rolling_mad_z` 上两侧可判定且与 `expected_merged` 一致（25 分钟合、35 分钟不合）。`missing_run` **只**由 `rules.missing_run` 覆盖——缺失点在滚动检测器里不可评分，是设计不是漏检。
  - 周期：稳妥 ACF 逐 series 得 288/287/289 → 运行级**中位数 288**（与生成器 24h@5min 的植入周期一致），`period_source=estimated` 写进 `run.json`。
  - 冻结指纹：异常集 sha256 `6020a3d34b0228c9b0735d7b2d10aad67d3181d0cb02eb2a02d7fd864ef1b422`（178 episodes / 653 detections / 7 条检测器流），字面量钉在 `selftest.GOLDEN_ANOMALY_DIGEST` 与 `tests/test_detect.py`、`tests/test_selftest.py` 三处。
  - **改参数必改哈希**：`tests/test_detect.py` 对参数面 **20 项逐项**断言、`selftest` 在冻结 fixture 上另断言 6 项（含 `max_gap_ms` 与周期声明）；另加两条行为断言（收紧 `max_gap_ms` → episode 变多；抬高 `k` → 变少）。
  - **变异验证 16/16 变红**（`.tmp/mutate.py` 风格：替换前三连断言；每条都指名了变红的测试）。其中 **1 条最初仍绿**：`rolling_mad_z` 的 `> k` 严格性无测试钉住 → 补 2 条边界测试（严格大于；IQR 界上恰好不判）后才变红。
  - **无超越函数门实测抓出真实违规**：`canon.py` 的 `10 ** decimals` 已改为连乘 `_power_of_ten`（哈希路径禁 `**`）；门覆盖 `src/anomaly_atlas/`（12 个 py）+ **`*.js` 词法**（M3 的镜像是 `src/anomaly_atlas/mirror/zaa_mirror.js`，落在 src 下 → **自动被现有门覆盖**）+ 显式豁免表（当前为空，机制本身有测试）+ 7 条变异（含 JS 的 `Math.exp` 与 `**`）。
  - `selftest` 五项检查**探针全红**：篡改台账字节 / 追加不可覆盖的植入段（**注意探针方向**：删一段只会让要求一起消失、检查照样绿）/ 错误黄金字面量 / 同一 spec 指纹必须不变 / 改时区字节必变；探针不变红即计为失败；找不到冻结数据 → **exit 4**。
  - 退出码冒烟 16 条逐条实测：0（`--help`/`--version`/`profile`×2/`detect`×2/`selftest`）、2（无参数/未知子命令/`profile` 缺参/缺文件/`detect` 缺文件/`verify` 缺产物）、3（`render`/`verify`(有产物)/`check-report`），失败路径**零副作用**（不建目录不写文件）。
- **数据侧修复（D19，重要）**：M2 实测发现 M1 冻结数据里 humidity 的植入尖峰（1800–2200 milli）**低于它自己的噪声幅度（600 milli）**，`k=3.5` 下最大 z 只有 **2.77**（row 1694）→ 任何可用阈值都检不出，且其日周期（910 milli 摆幅）只有噪声的 1.5 倍、无周期估计器能找到。修复 = 只把该指标噪声幅度降到 **200 milli**（不动植入幅度/行号/段数/布局），并给生成器加**可检出性下限断言**（加性幅度 ≥ 8× 噪声幅度、日周期摆幅 ≥ 3× 噪声幅度）。**真值指纹 `ad3822a1…` 不变**；`series.csv`/`manifest.json`/`truth.json` 的 sha256 已更新、`hash.txt` 字节不变；`--check` 两层仍绿。
- **诚实口径**：**未接远端，CI 待首推验证**。CI 已补四步冒烟（`detect` 双跑逐字节 + 指纹文件与归档自对账 + 裸 console script `detect` + `selftest`），**均未实跑**；ubuntu 腿与 CI 步骤形态仍属本地等价校验缺口。

## 2. 下一棒待办（M3 浏览器复算硬门禁）

1. **`src/anomaly_atlas/mirror/zaa_mirror.js`（手写 JS 镜像）**：实现 `parse`（**复用内联的整数毫秒**，只做算法）、`detect`（4 类）、`episodes`（合并/排序/id）、`canonicalJson`（键排序 + 整数定点）、`sha256`（自实现，禁 `crypto.subtle`）。
   - **不需要**重实现周期估计器：镜像**消费 `run.json` 里的生效 `period_points`**（K8/D13）——这正是"生效值写进 run.json"的收益，务必别把它变成第二份估计器。
   - 需要重实现的口径细节（`data/README.md` §4.1 是权威）：尾部对齐含被评点的窗口、`min_valid` 降级、**MAD=0/IQR=0 回退到平均绝对偏差**、尺度为 0 不判、STL（LOESS tricube + **相位取自栅格下标** + 三倍复制相位轴 + bisquare）、`rules` 四条（含 CUSUM 差分标准化 + **报警重置** + 差分尺度退化时不表态）、`quantize` 半偶舍入（**`10^d` 必须写成连乘**）、`fixed_to_str`、合并（`≤ max_gap_ms`，按 `(series, detector)` 分组）、严重度键、`episode_id`。
   - 栅格下标重建（`(ts − ts0) / cadence`）与 cadence 都从内联数据/run.json 取（cadence 已在 run.json 的 `series` 块里）。
2. **HTML 内嵌契约（M3 定，M4 复用）**：原始数据按 series 的行数组 `[ts_ms, value|null]` + `run.json` + **构建时**规范 JSON（异常集）+ 构建时 sha256 + 镜像源码。M3 先落一个**最小载体页**用于自动对账；`render.py`（M4）复用同一嵌入契约做真正的标注图。
3. **`tools/mirror_parity.py --html <产物> [--node <exe>]`**：从产物里抽出内联镜像与数据，用 Node 执行同一流程，与 Python 构建指纹对账。**这是 M3 的可自动化门禁**（浏览器徽章是人读面）。Node 缺失 → **exit 4** 并给两条安装/替代路径，**不允许静默跳过**；`--tamper-index <n>` 改一个内联点 → 必须 MISMATCH 且**定位到该点**（探活打在消费处：从产物里抽出的内联数据）。
4. **SHA-256 已知向量双侧断言**：空串、`"abc"`、长于 55 字节、长于 64 字节；Python 侧 `hashlib`、JS 侧自实现，共用同一组向量。
5. **测试**：`tests/test_mirror.py`（JS 词法/结构 + 向量 + 篡改定位 + Node 缺失 → exit 4）+ 扩展 `tests/test_render.py`（M3 的最小载体页：零外链、双跑逐字节、内嵌指纹自洽）。
6. **K1 退役第三步（同一提交内五处同步）**：`verify` 落地 → `STAGE_NOT_READY` 删 `verify` 键 → CLI 接线（已预置）→ 测试（`test_skeleton.py` 注册表不变、not-ready 用例自动 skip）→ 文档退出码表与 README 状态表 → 决策记录补一条；**CI 同提交补 `verify`/`mirror_parity` 离线冒烟**（Node 在 runner 上预装 → 门禁能真跑）。
7. **收尾**：DoD 验证（双解释器 + 干净 venv + 变异验证）→ `plan/00·02·03·05·06` 状态回写 → 写 `plan/HANDOFF-M4.md` → 删除临时目录与 venv → commit。

## 3. 既定口径清单（K，动了会打挂测试）

- **K1 退出码契约（D8）**：0 成功 / 1 门禁或自检发现缺陷 / 2 用法与输入错误 / 3 阶段未就绪 / 4 环境前提不满足。`STAGE_NOT_READY` 现为 **`{verify:M3, render:M4, check-report:M5}`**；落地一个键**整项退役**、五处同步（常量 → CLI 接线 → 测试 → 文档 → 决策记录）；空后删除 `EXIT_NOT_READY` 常量。
- **K2 序列化冻结**：JSON 落盘统一走 `canon.canonical_json_bytes`（`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行）；**产物里禁时钟字段**；`profile.json`/`run.json` 里**没有任何 ISO 串**（时间一律整数 epoch 毫秒；ISO 只出现在 `anomalies.json` 的 Episode `start`/`end`），测试两者都断言。
- **K3 规范 JSON 只含整数与字符串**：`canon.assert_hashable` 在落盘出口拒浮点；`quantize` 半偶舍入（`quant_decimals` 默认 6）、`fixed_to_str` 由整数构造十进制串；**十进制的检测器参数以 6 位定点字符串落 `run.json`**（人读 == 被哈希，单一表示）。
- **K4 数值可镜像**：哈希/判定路径只允许 `+ - * / floor ceil abs min max` 与比较；幂次展开为连乘（`canon._power_of_ten`）；**禁一切超越函数与库归约函数**。门在 `tests/test_no_transcendental.py`：AST（py）+ 词法（js）+ 豁免表 + 变异；**`src/anomaly_atlas/mirror/zaa_mirror.js` 自动在扫描范围内**——JS 侧同样要守住 `Math.exp/pow/sqrt/log/trig/hypot/round` 与 `**`。**Python 与 JS 的 % / // 语义差异**：相位与整除只允许**非负操作数**（栅格下标、`Math.floor(a/b)`）。
- **K5 时间口径**：UTC **整数 epoch 毫秒**；落盘 ISO 定点串由整数反算；小数秒**截断**不四舍五入；无偏移输入按 `timezone_offset_min` 解释并记录。镜像**不重实现时间解析**（内联的已是整数毫秒）。
- **K6 排序与 tie-break**：所有排序给**全序比较器**（含源行号 index tie-break），禁止依赖引擎稳定性；Episode 严重度键 = `peak_score_q` 降 → `duration_ms` 降 → `start_row` 升 → `detector` 字典序；`episode_id = "<series_id>-E<NNN>"`（**按 series 计数**，全局计数会让增删 series 时无关 id 漂移）。
- **K7 Episode 合并**：时间域 `max_gap_ms`（整数毫秒）；相邻异常点时间差 **≤** 该值即合并（严格边界有测试）；**按 `(series_id, detector)` 分组**合并；与剖面的"缺口区间"是两个概念（D18c）。真值的 `merge_probes[].expected_merged` 是判据；`rolling_mad_z` 是**探针主检测器**（它在这 6 对上的判定集恰好是两个植入点）。
- **K8 参数面与生效值**：`run.json` 记录**解析后的最终值**（含 ACF 估出的 `period_points`、`period_reject_*`、`max_gap_ms`、`quant_decimals`、算法/规范版本号）；复算侧消费生效值、**不重跑估计**；引擎里不留隐形默认——默认值有**逐字 golden 断言**（`tests/test_detect.py::TestDefaultsArePinned` + `tests/test_profile.py::TestDefaultsArePinned`），改默认必须同时改测试。**生效参数块在异常集指纹里**（只哈希 episode 会让"改参数必改哈希"在"判定没动"时失效）。
- **K9 数据契约与错误码**：`csvio.ERROR_CODES` 单点定义（7 个）+ 文档表互等门；行号 = 物理行号（`csv.reader.line_num`）；一次报全部错误。容差默认：`duplicate_timestamp_max=1`、`non_monotonic_max=0`；缺失标记 → `None`（**不补 0 不插值**）。
- **K10 编码守卫**：`cli.py` 是 `_ensure_utf8_stdio()` 的单点定义，`tools/` 下每个可执行入口导入并调用它（新增脚本必须补挂）；子进程读写显式 `encoding=`；CI env `PYTHONUTF8=1`。
- **K11 生成器纪律**：splitmix64 自研 RNG（禁 `random`，参考向量 KAT）；seed 显式传参并写 manifest；`--check` 两层断言；真值只存输入与期望、禁 `observed`；**生成器断言真值非平凡且可检出**（段数 + 窗口边界 + 探针两侧 + 重复戳 + 缺口/缺失/零值 + **幅度下限 ≥ 8× 噪声幅度、日周期摆幅 ≥ 3× 噪声幅度**）。
- **K12 零外链**：`render` 出口常驻 `assert_no_external_resources(html)`（M4）；M3 的最小载体页也必须零外链（镜像内联、无 CDN、无外链字体）。**HTML 加载时不得发起任何网络请求**。
- **K13 复算指纹一致性**：`canonical_json_bytes`/`quantize`/`fixed_to_str`/`sha256_hex`/`canonical_digest` 是**唯一**实现；JS 镜像必须逐字节产出同一份规范 JSON。**M3 的硬门禁**：未通过 Node 对账的 HTML 不构成交付物（`tools/mirror_parity.py` exit 0 才算）。
- **K14 数字白名单**：报告数字必须命中 `facts.json`（M5）。
- **K15 不留桩（D14）**：未落地模块**不产** `NotImplementedError`/`pass`/`return 0` 桩；`tests/test_skeleton.py::TestNoSentinelStubs` 常驻扫描 `src/`+`tools/`（含正向对照与变异）。**新增 JS 文件也在扫描范围内**（`.js` 会被哨兵扫描器扫到）。
- **K16 命令注册表三处同步**：`cli.COMMANDS` / `cli.STAGE_NOT_READY` / 测试侧 `_ARGS_BY_COMMAND` + `_INPUT_FILES`；新增子命令必须同时补三处。
- **K17 冻结数据的已知形状**（post-D19）：`data/synthetic/series.csv` 是按 (时间, series) 交错的长表（同一 series 相邻行号相差 3）；温度行含 1 个重复时间戳；四种时间戳表示成块交替（剖面报 2 次 `offset_switches`、900 行 implicit）；缺失写成空串、零值写成 `0.00`；每 series 各有 1 处时间缺口；**humidity 噪声幅度现为 200 milli**（D19）。
- **K18（M2 新增）指纹黄金值与探针方向**：异常集指纹黄金值 `6020a3d3…` 钉在三处；**任何**检测算术或数据改动都会让它变红——这是**故意的跳线**，改它必须是有意识的动作。`selftest` 的覆盖类探针必须**增加**一项无法满足的要求（删段只会让要求一起消失）；探针不变红计为失败。
- **K19（M2 新增）报告口径的"39 段"不是"39 个 episode"**：探针两侧的"25 分钟"三对**必须合并**成一个 episode（K7 字面规则），所以 39 段真值对应 36 个 spike 系 episode 是**正确**的；对账判据是**覆盖**（逐段被至少一个 episode 覆盖）而不是数量相等。当前默认 spec 全量输出 178 episodes / 653 detections（7 条检测器流，多检测器交叉证据是设计意图）。

## 4. 本机环境坑（只写实测过的）

- 用 `py` 不是 `python`；一律 `py -X utf8`。本机 **3.8.8 与 3.12.10** 两条通道；每棒双解释器全量跑；跨版本差异只能靠 CI。
- 全程 `PYTHONDONTWRITEBYTECODE=1`；源模式跑测：`PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/ -q`。
- pip 装包必须 `NO_PROXY="*" no_proxy="*"` + 清华镜像；`py -3.12 -m venv .venv-verify` + `pip install -e ".[dev]"` 一次成功（本轮实测）；**验证用 venv 用完立刻删**。
- Git Bash 的 `/tmp` 与 Windows 原生 Python 不通：临时文件用仓库内相对目录（`.tmp/`，已 gitignore）或系统临时目录。
- **本机没有 Node**（M1/M2 都没验过）：M3 的 `mirror_parity` 在本机会走 exit 4 分支——**要么装 Node，要么如实记录"本机不可自动化"并在 CI（ubuntu runner 有 Node）跑**；不要把它写成"已验证"。
- **性能**：纯 Python 检测管道在冻结数据上约 **2 s**（`detect` 全流程），其中 STL 的趋势 LOESS 是热点——已用"tricube 权重表按半径缓存 + 内层循环一次字典/列表索引"把 `detect_all` 从 3.8 s 压到 1.24 s（**语义逐字节不变**：优化前后指纹相同）。`selftest` 约 12 s（含 7 次全量检测）；全量套件 3.12 34 s / 3.8 44 s / venv 47 s。测试用 **module-scoped fixture** 共享一次管道跑（别在测试里反复跑全量）。
- `pytest` 的 `capsys` 是 **function-scoped**：不要把它塞进 module-scoped fixture（会 `ScopeMismatch`）；需要"只跑一次并捕获输出"就用 `contextlib.redirect_stdout` + 模块级缓存。
- **变异脚本必须三连断言**（替换前 marker 唯一 → 替换后字节已变 → 还原后字节一致），且要**指名期望变红的测试**；本棒 `.tmp/mutate.py` 就是这么写的（16 条）。第二种假绿：测试把期望值从"被测产物自身"读回来——**写断言优先用字面量 pin 住契约**。
- **AST 细节**：`ast.Pow` 是**算符节点、没有 `lineno`**——要检测 `**` 必须看 `ast.BinOp(op=Pow)` 与 `ast.AugAssign(op=Pow)`；`ast.Name` 扫名字会把局部变量（如 `median`）误报，只扫**调用**与**属性**。

## 5. DoD 逐项 checklist（M3 出口）

- [ ] `src/anomaly_atlas/mirror/zaa_mirror.js`：手写镜像（parse 复用内联毫秒 / 4 类检测 / episodes / canonicalJson / 自实现 SHA-256），**与 Python 同操作序列**，过 `test_no_transcendental` 的 JS 词法门
- [ ] 内嵌契约 + 最小载体页：内联数据/run.json/构建时规范 JSON/构建时 sha256/镜像源码；**零外链**；双跑逐字节
- [ ] `tools/mirror_parity.py`：Node 对账逐位一致（正常产物）；`--tamper-index n` **必变红并定位到第 n 点**；Node 缺失 → **exit 4** 且给两条补救路径（不静默跳过）
- [ ] SHA-256 已知向量（空/`abc`/>55B/>64B）**双侧断言**（Python `hashlib` 与 JS 自实现）
- [ ] 测试文件（`tests/test_mirror.py` 等）+ **变异验证**（往镜像里塞 `Math.exp`/改一处分位/改合并边界 → 必须变红）
- [ ] **K1 退役第三步**：`verify` 从 `STAGE_NOT_READY` 删除并接线真实现，五处同步完成；CI 同提交补 `verify`/`mirror_parity` 离线冒烟
- [ ] 三处全绿（3.8 / 3.12 / 干净 venv）+ 退出码冒烟逐条实测（含**零副作用**与 Node 缺失的 exit 4）
- [ ] `plan/00·02·03·05·06` 状态回写 + `plan/HANDOFF-M4.md` 六节齐落盘并 commit
- [ ] CI 首推全绿 —— **未接远端，待 M6 首推验证**（不可本机实跑；ubuntu 腿与 CI 步骤形态是本地等价校验的缺口）

## 6. 关键命令速查

```bash
cd <repo>
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1

py -3.12 -X utf8 -m pytest tests/ -q          # 全量测试（3.8 同；约 34 s / 44 s）
py -3.12 -X utf8 -m pytest tests/test_detect.py -q

py -3.12 -X utf8 -m anomaly_atlas.cli detect data/synthetic/series.csv --out-dir out
cat out/anomaly_set.sha256                     # 6020a3d3…
py -3.12 -X utf8 -m anomaly_atlas.cli selftest # 5 检查 + 5 探针，全绿 → exit 0
py -3.12 -X utf8 tools/gen_synthetic_series.py --check

# M3 落地后
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html                 # Node 对账，exit 0 才算交付
py -3.12 -X utf8 -m anomaly_atlas.cli verify examples/atlas.html --tamper-index 3 # 必须 MISMATCH 并定位
py -3.12 -X utf8 tools/mirror_parity.py --html examples/atlas.html

# 安装跑法（本机实测一次成功；验证完删 venv）
py -3.12 -m venv .venv-verify
NO_PROXY="*" no_proxy="*" ./.venv-verify/Scripts/python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv-verify/Scripts/python.exe -m pytest -q
./.venv-verify/Scripts/anomaly-atlas.exe selftest
```
