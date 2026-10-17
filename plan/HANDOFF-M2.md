# HANDOFF-M2（M1 已收尾 → 下一棒 M2 检测内核）

> 用法：新对话 `/goal 读取 <项目绝对路径>\plan\HANDOFF-M2.md 继续完成任务`（库内一律相对路径）。

## 1. 当前进度 + 证据

- **M1 数据先行已完成**。今天有真实行为的模块：`cli.py`（退出码契约 + 编码守卫 + 编排）、`timebase.py`（K5 整数时间轴）、`csvio.py`（K9 契约解析 + 7 错误码）、`profile.py`（剖面 + 质量卡 → `profile.json`）、`canon.py`（**K2/K3 原语**：`quantize`/`fixed_to_str`/`canonical_json_bytes`/`sha256_hex`/`assert_hashable`）、`tools/gen_synthetic_series.py`（K11 splitmix64 生成器 + `--check` 守门）。其余 7 个模块（`detect`/`episodes`/`layout`/`render`/`facts`/`report`/`mirror`/`selftest`）仍为 **docstring-only**（不产桩，D14）。
- **冻结资产已入库**：`data/synthetic/series.csv`（2961 行 / 127131 B）、`data/synthetic/manifest.json`（3257 B）、`data/truth/truth.json`（18723 B）、`data/truth/hash.txt`（真值 sha256 `ad3822a14c95dd3478eeea1c58090bc1cd1afd0eea3f82aed91588a9f0b75d5c`）、`data/samples/minimal.csv`（17 行手写）。
- **证据（本轮实测）**：
  - 三处全绿：`py -3.8` / `py -3.12` / 干净 venv（3.12 + `pip install -e ".[dev]"`）各 **211 passed, 1 skipped**（skip = `profile` 的 not-ready 用例按设计退役）；venv 产出的 `profile.json` 与源码直跑**逐字节相同**（`cmp` 实测）；无警告。
  - **时间换算被标准库证伪**：全量 2960 行 fixture 逐行与 `datetime`（`strptime` + `timedelta` 整数重组）交叉断言相等；另加 1800–2200 年 `toordinal` 对照、4000 组随机 epoch 反算、闰日/月末/年末/世纪闰年/9 位小数截断/无秒/无偏移按声明时区；两条**可证伪探针**（off-by-one 算法必被交叉断言拒掉；截断 vs 四舍五入）。
  - **真值非平凡**：39 段（spike 22 / level_shift 5 / variance_shift 6 / missing_run 3 / zero_run 3）、6 条 `max_gap_ms` 两侧合并探针（25 分钟 vs 35 分钟，阈值 30 分钟）、3 处缺口、3 段缺失、3 段零值、1 个重复时间戳（同时是 tie 样本）；6 段落在滚动窗口边界（两侧都有）。
  - **两层守门**：`--check` 台账（逐文件 sha256）+ 重生成逐字节比对皆绿；篡改 `series.csv`、删 `truth.json`、篡改 `hash.txt`、篡改 **manifest 自身**、删 manifest —— 五种损伤逐条实测 **exit 2**。
  - **变异验证 10/10 变红**（days_from_civil / ISO 宽度 / 行号来源 / 缺失标记 / 规范 JSON / 隐藏默认 / 缺口检测 / splitmix64 常数 / `--check` 重生成比对 / 文档错误码表）。**其中 2 条最初仍绿**，暴露出两处测试弱点（见 §4），已修测试后变红。
  - 退出码冒烟 12 条逐条实测：`--help`/`--version` → 0；无参数 / 未知子命令 / `profile` 缺参 / `profile` 缺文件 / `detect nope.csv` / `verify` 缺产物 → 2；`profile` 真跑（`minimal.csv` 与 `series.csv`）→ 0；`detect`/`render`(有输入)/`check-report`/`selftest` → **3（not ready）**，零副作用。
  - 安装面：`py -3.12 -m venv .venv-verify` + `pip install -e ".[dev]"`（清华镜像 + `NO_PROXY="*"`）一次成功；裸 console script `anomaly-atlas --version` → `anomaly-atlas 0.1.0`，`anomaly-atlas profile data/synthetic/series.csv -o …` → 0；**验证完 venv 已删**，`git status` 干净。
- **诚实口径**：**未接远端，CI 待首推验证**（workflow 已补 `profile` 双跑冒烟、裸 console script 冒烟与生成器 `--check` 冒烟，但从未被实跑；ubuntu 腿与 CI 步骤形态是本地等价校验的缺口）。

## 2. 下一棒待办（M2 检测内核）

1. `canon.py` 补齐 M2 面：`build_anomaly_set(run_spec, rows/profile, episodes)` → 规范 JSON（整数/字符串 only）+ sha256；`run.json` 落盘（**解析后的生效值**：含 ACF 估出的 `period_points`、`max_gap_ms`、`quant_decimals`、算法/规范版本号）。
2. `detect.py` 四类检测器（参数面 `data/README.md` §4.1，默认值 `plan/06` P4）：`rolling_mad_z{window:24,k:3.5}`、`rolling_iqr{window:24,iqr_mult:3.0}`、`stl_resid_z{inner:2,outer:1,window:24,k:3.5}`、`rules{static_threshold:null,pct_jump:0.35,missing_run:6,cusum_k:0.5,cusum_h:5.0}`。**MAD=0 特例必须写进口径表**（不许靠"除零得 inf 再比较"）；滚动类在窗口内有效点 < `min_valid` 时**不高判**；规则型按连续性判；缺失/零值段不是"可跳过的东西"。`period_points` 由 ACF 估计或用户声明，**生效值写入 run.json**。
3. `episodes.py`：相邻异常点按**时间域** `max_gap_ms=1800000` 合并（K7）；Episode 字段 `episode_id`/`series_id`/`detector`/`start`/`end`/`start_row`/`end_row`/`n_points`/`duration_ms`/`peak_score_q`/`threshold_ref`；严重度键 `peak_score_q` 降 → `duration_ms` 降 → `start_row` 升 → `detector` 字典序（K6，**禁止原始浮点排序**）；`episode_id = "<series_id>-E<NNN>"`。
4. `selftest.py` 基准套件：对 M1 真值**全段对账**（39 段逐段，非抽样）+ fixture 哈希固化 + **改任一参数 / `max_gap_ms` / 周期声明，哈希必变**（断言）。
5. 测试：`tests/test_canon.py` / `test_detect.py` / `test_episodes.py` / `test_selftest.py` / **`test_no_transcendental.py`**（`ast` 白名单扫 `src/anomaly_atlas/` + JS 词法 + 显式豁免表，带**变异验证**：往检测路径塞一个 `math.exp` → 门必红）。
6. **K1 退役第二步（同一提交内五处同步）**：`detect` 与 `selftest` 落地 → `STAGE_NOT_READY` 删这两个键 → CLI 接线（已预置）→ 测试（`tests/test_skeleton.py` 的 `_ARGS_BY_COMMAND`/`_INPUT_FILES` 保持不变，not-ready 用例自动 skip；新增测试文件覆盖真实行为）→ 文档退出码表/README 当前状态表更新 → 决策记录补一条；**CI 同提交补 `detect`/`selftest` 离线冒烟**。
7. 收尾：DoD 验证（双解释器 + 干净 venv + 变异验证）→ `plan/00·02·03·05·06` 状态回写 → 写 `plan/HANDOFF-M3.md` → 删除临时目录与 venv → commit。

## 3. 既定口径清单（K，动了会打挂测试）

- **K1 退出码契约（D8）**：0 成功 / 1 门禁或自检发现缺陷 / 2 用法与输入错误 / 3 阶段未就绪 / 4 环境前提不满足。`STAGE_NOT_READY` 现为 `{detect:M2, selftest:M2, verify:M3, render:M4, check-report:M5}`；模块落地时对应键**整项退役**，五处同步（常量 → CLI 接线 → 测试 → 文档 → 决策记录）；`STAGE_NOT_READY` 空后删除 `EXIT_NOT_READY` 常量。
- **K2 序列化冻结**：JSON 落盘统一走 `canon.canonical_json_bytes`（`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行）；**产物里禁时钟字段**；`profile.json` 里**没有任何 ISO 串**（时间一律整数 epoch 毫秒），测试两者都断言。
- **K3 规范 JSON 只含整数与字符串**：`canon.assert_hashable` 在落盘出口拒浮点；`quantize` 半偶舍入（`quant_decimals` 默认 6）、`fixed_to_str` 由整数构造十进制串；**禁浮点格式化参与哈希**（口径见 `data/README.md` §4.3）。
- **K4 数值可镜像**：哈希路径只允许 `+ - * / floor ceil abs min max` 与比较；幂次展开为连乘；**禁一切超越函数与库归约函数**。生成器已用 **24 点日剖面表 + 线性插值**替代 `sin`，并有 AST 门断言 `tools/` 与 `canon.py` 路径上无 `exp/log/pow/sin/cos/sqrt` 调用、无 `**`、无 `random`。M2 要给 `src/` + JS 镜像加同款扫描门（Python AST + JS 词法）+ 变异验证。
- **K5 时间口径**：UTC **整数 epoch 毫秒**；落盘 ISO 定点串 `YYYY-MM-DDTHH:MM:SS.mmmZ` 由整数反算；无偏移输入按 `timezone_offset_min`（默认 0=UTC）解释**并记录**（`profile.time.distinct_offsets` / `offset_switches` / `n_implicit_offset_rows`）；小数秒**截断**不四舍五入；世纪闰年规则由 `civil_from_days(days_from_civil(...))` 反算校验。
- **K6 排序与 tie-break**：所有排序给**全序比较器**（含源行号 index tie-break），禁止依赖引擎稳定性；Episode 严重度键 = `peak_score_q` 降 → `duration_ms` 降 → `start_row` 升 → `detector` 字典序；`episode_id = "<series_id>-E<NNN>"`。
- **K7 Episode 合并**：时间域 `max_gap_ms`（整数毫秒）；相邻异常点时间差 ≤ 该值即合并。**与剖面的"缺口区间"是两个概念**（D18c）：剖面缺口 = 间隔 > `gap_factor(3) × 主导节奏`，登记采样节奏异常；合并只按 K7 字面规则。合成数据在 `max_gap_ms` 两侧各留探针（25 分钟必须合并 / 35 分钟必须不合并），truth 的 `merge_probes[].expected_merged` 是判据。
- **K8 参数面与生效值**：`run.json` 记录**解析后的最终值**；复算侧消费生效值、不重跑估计；**引擎里不留隐形默认**——`profile.py` 的 `DEFAULT_SPEC` 有一份**逐字 golden 断言**（`tests/test_profile.py::TestDefaultsArePinned`），改默认必须同时改测试。
- **K9 数据契约与错误码**：`csvio.ERROR_CODES` 单点定义（7 个），且 `data/README.md` §4.4 的表格与代码**互等**断言（文档漂移门）。**行号 = 物理行号**（`csv.reader.line_num`，表头 = 第 1 行，一次报全部错误、每条带行号或列名）。**容差默认值**：`duplicate_timestamp_max=1`（同一 series 内允许 1 处重复戳，登记进剖面；超阈值 → `E_DUPLICATE_TIMESTAMP`）、`non_monotonic_max=0`（任何乱序即错 → `E_NON_MONOTONIC`）。缺失标记（空串/`NA`/`N/A`/`NaN`/`null`/`none`/`-`/`--`）→ `None`，**不补 0 不插值**；非有限数与 `1_000`/`0x10` 形态一律 `E_VALUE_UNPARSEABLE`。
- **K10 编码守卫**：`cli.py` 是 `_ensure_utf8_stdio()` 的单点定义，`tools/` 下每个可执行入口**导入并调用**它（`tools/gen_synthetic_series.py` 已如此；新增脚本必须补挂）；子进程读写显式 `encoding=`；CI env `PYTHONUTF8=1`。
- **K11 生成器纪律**：splitmix64 自研 RNG（**禁 `random`**，`tests/test_generator.py` 用**已发布参考向量**做 KAT：seed 0 → `0xE220A8397B1DCDAF`, `0x6E789E6AA1B965F4`, `0x06C45D188009454F`）；seed 显式传参并写入 manifest；`--check` 两层断言；**真值只存输入与期望、禁 `observed`**、禁恒哑 `status` 键；生成器自身断言真值非平凡（每类 ≥2 段 / 有窗口边界段 / 探针两侧齐 / 有重复戳 / 有缺口-缺失-零值）。
- **K12 零外链**：`render` 出口常驻 `assert_no_external_resources(html)`（M4）。
- **K14 数字白名单**：报告数字必须命中 `facts.json`（M5）。
- **K15 不留桩（D14）**：未落地模块**不产** `NotImplementedError`/`pass`/`return 0` 桩；`tests/test_skeleton.py::TestNoSentinelStubs` 常驻扫描 `src/`+`tools/`（带正向对照与变异用例）。**注意**：`tools/gen_synthetic_series.py` 里出现了 `pass` 吗？没有——但新增工具脚本时别写空 `pass` 分支，扫描器会红。
- **K16 命令注册表三处同步**：`cli.COMMANDS` / `cli.STAGE_NOT_READY` / 测试侧 `_ARGS_BY_COMMAND` + `_INPUT_FILES`。**新增子命令必须同时补这三处**。
- **K17（M1 新增）冻结数据的已知形状**：`data/synthetic/series.csv` 是**按 (时间, series) 交错**的长表（行号稀疏，同一 series 相邻行号相差 3）；温度行含 **1 个重复时间戳**（在默认容差内，剖面登记为 `duplicate_timestamps`）；四种时间戳表示形式**成块**交替（`Z` / `+08:00` / 空格分隔无偏移 / `Z`）→ 剖面会报 2 次 `offset_switches`、900 行 implicit；缺失值写成**空串**、零值写成 `0.00`；每 series 各有 1 处时间缺口。**M2 的检测与合并必须能在这份文件上跑出与 truth 一致的 39 段**。

## 4. 本机环境坑（只写实测过的）

- 用 `py` 不是 `python`（后者是商店占位符）；一律 `py -X utf8`。本机有 **3.8.8 与 3.12.10 两条通道**；每棒双解释器全量跑；**跨版本差异只能靠 CI**。
- 全程 `PYTHONDONTWRITEBYTECODE=1`；源模式跑测：`PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/ -q`。
- pip 装包必须 `NO_PROXY="*" no_proxy="*"` + 清华镜像；本轮 `py -3.12 -m venv .venv-verify` + `pip install -e ".[dev]"` 一次成功。**验证用 venv 用完立刻删**。
- Git Bash 的 `/tmp` 与 Windows 原生 Python 不通：临时文件用仓库内相对目录（本轮用 `.tmp/`，`.gitignore` 已忽略）或系统临时目录。
- **`csv.reader` 的物理行号**：用 `reader.line_num`（记录**结束**行）而不是自己数 enumeration，否则带前导空行 / 引号内换行的文件行号会错——本轮变异验证正是靠这一点变红。
- **变异脚本必须三连断言**（替换前 marker 唯一存在 → 替换后字节已变 → 还原后字节一致）。本轮暴露出**第二种假绿**：测试把期望值从"被测产物自身"里读回来（如 `document["params"]["gap_factor"]`），于是默认值漂移时测试跟着漂。**写断言时优先用字面量 pin 住契约**，再加一条 golden 默认值表。
- argparse 未知子命令与缺必需参数都抛 **`SystemExit(2)`**；`cli.main` 对未知子命令返回 2，对"缺文件"在 import 前就返回 2。
- `tools/` 下的脚本在文件顶部把 `src` 插进 `sys.path`（源码模式与安装模式都能跑），并 `from anomaly_atlas.cli import _ensure_utf8_stdio`（K10 单点定义）。
- 默认分支 `main`，git 身份 `yuluo554 <282769740+yuluo554@users.noreply.github.com>`；`gh` 已登录 `yuluo554`（scopes 含 repo）。

## 5. DoD 逐项 checklist（M1 出口）

- [x] `timebase.py`（K5）：纯整数 civil↔epoch + ISO 定点反算；**全量 fixture 行被 `datetime` 交叉证伪**；闰日/月末/年末/世纪闰年/偏移/小数秒/无秒/无偏移按声明时区全覆盖；**两条可证伪探针**
- [x] `csvio.py`（K9）：7 错误码单点定义 + 文档表互等门；错误带**物理行号**、**一次收集统一报出**；列名同义词白名单 + 歧义即报错；缺失 → `None`（不补 0 不插值）
- [x] `profile.py`：`profile.json` 双跑 **byte-identical**（源码模式与安装面产出同一份字节）；节奏/缺口/零值段/缺失段/重复时间戳/非单调 + 质量卡；**只含整数与字符串、无时钟字段、无 ISO 串**；`TestDefaultsArePinned` 锁默认值
- [x] `tools/gen_synthetic_series.py`（K11）：splitmix64（参考向量 KAT）+ 场景"冷链仓储温控与能耗监测（虚构）"+ 3 series × 1000 点；四类异常各 ≥2 段、窗口边界段、`max_gap_ms` 两侧探针、重复戳、缺口/缺失/零值；`data/synthetic/{series.csv,manifest.json}` + `data/truth/{truth.json,hash.txt}`；`--check` 两层 + 五种损伤 exit 2
- [x] `data/samples/minimal.csv`：17 行手写，可人眼核对（1 缺口 + 1 缺失 + 2 点零值段）
- [x] 四个测试文件（`test_timebase` / `test_csvio` / `test_profile` / `test_generator`）+ `tests/conftest.py`
- [x] **K1 退役第一步**：`profile` 从 `STAGE_NOT_READY` 删除并接线真实现；五处同步完成；`test_skeleton.py` 注册表保持不变、not-ready 用例自动 skip
- [x] CI 同提交补 `profile` 离线双跑冒烟 + 裸 console script 冒烟 + 生成器 `--check` 冒烟
- [x] 变异验证 **10/10 变红**（含 2 处修测试后才变红）
- [x] 退出码冒烟 12 条逐条实测（含"零副作用"）；三处全绿 211 passed / 1 skipped；`plan/00·02·03·05·06` 状态回写；`plan/HANDOFF-M2.md`（本文档）六节齐落盘并 commit
- [ ] CI 首推全绿 —— **未接远端，待 M6 首推验证**（不可本机实跑；ubuntu 腿与 CI 步骤形态是本地等价校验的缺口）

## 6. 关键命令速查

```bash
cd <repo>
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1

py -3.8  -X utf8 -m pytest tests/ -q          # 全量测试（3.12 同）
py -3.12 -X utf8 -m pytest tests/ -q

py -3.8 -X utf8 -m anomaly_atlas.cli --help                       # exit 0
py -3.8 -X utf8 -m anomaly_atlas.cli --version                    # exit 0
py -3.8 -X utf8 -m anomaly_atlas.cli profile data/samples/minimal.csv -o profile.json   # M1 已落地，exit 0
py -3.8 -X utf8 -m anomaly_atlas.cli profile data/synthetic/series.csv -o profile.json
py -3.8 -X utf8 -m anomaly_atlas.cli detect  data/synthetic/series.csv --out-dir out    # M2 落地后；此前 exit 3
py -3.8 -X utf8 -m anomaly_atlas.cli selftest                                          # M2 落地后；此前 exit 3

py -3.8 -X utf8 tools/gen_synthetic_series.py            # 重新生成冻结资产（改库前先想清楚）
py -3.8 -X utf8 tools/gen_synthetic_series.py --check    # 台账 + 重生成逐字节；篡改/缺失 exit 2

# 安装跑法（本机实测一次成功；验证完删 venv）
py -3.12 -m venv .venv-verify
NO_PROXY="*" no_proxy="*" ./.venv-verify/Scripts/python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv-verify/Scripts/anomaly-atlas.exe profile data/synthetic/series.csv -o profile-venv.json
./.venv-verify/Scripts/python.exe -m pytest -q
```
