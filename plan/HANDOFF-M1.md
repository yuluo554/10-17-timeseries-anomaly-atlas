# HANDOFF-M1（M0 已收尾 → 下一棒 M1 数据先行）

> 用法：新对话 `/goal 读取 <项目绝对路径>\plan\HANDOFF-M1.md 继续完成任务`（库内一律相对路径）。

## 1. 当前进度 + 证据

- **M0 骨架已完成**（plan/02–06 计划文档、目录结构、`pyproject.toml`、CLI 退出码契约、CI 预置、测试、README/LICENSE）。
- 骨架在位：`src/anomaly_atlas/`：`cli.py`（编排 + 退出码契约 + 编码守卫，**唯一有行为的模块**）、`__init__.py`（`VERSION = "0.1.0"`）、其余 12 个模块为 **docstring-only**（声明计划 API，无任何可执行桩）；`tests/test_skeleton.py`；`.github/workflows/ci.yml`（windows/ubuntu × 3.8/3.12 四矩阵，`PYTHONUTF8=1`）；`.gitattributes`（`* text=auto eol=lf`）。
- **证据（本轮实测）**：
  - 双解释器 pytest：`py -3.8` 31 passed、`py -3.12` 31 passed；干净 venv（3.12 + `pip install -e ".[dev]"`）31 passed。
  - 退出码冒烟 14 条逐条实测：`--help`/`--version` → 0；无参数/未知子命令 → 2；五个需文件子命令缺文件 → 2；六个子命令输入存在 → **3（not ready）**；**零副作用**（未写出任何假产物）。
  - 安装面：`py -3.12 -m venv` + `pip install -e .`（清华镜像 + `NO_PROXY="*"`）一次成功；裸 console script `anomaly-atlas --version` → `anomaly-atlas 0.1.0`；`requires` 只有 `pytest>=7; extra == "dev"`（**零运行时依赖**）。
  - **变异验证 4/4 变红**（哨兵串门 / 编码守卫 / 输入前置检查 / not-ready 契约各注入一处缺陷 → 目标测试必红，且还原后字节一致）。变异脚本三连断言（marker 存在 → 文件已变 → 还原字节一致），用完即删（未入库）。
- **诚实口径**：**未接远端，CI 待首推验证**（workflow 预置但从未被实跑；首推预算至少一轮诊断）。本地等价校验 = 双解释器全量 pytest + 干净 venv 全量 pytest + 退出码冒烟矩阵 + 变异验证；**不可本机实跑的通路** = GitHub 四矩阵 ubuntu 腿与 CI 的 console-script 步骤（已在本机用 venv 裸命令等价覆盖，但不是同一件事）。

## 2. 下一棒待办（M1 数据先行）

1. `timebase.py`（K5）：`parse_iso_to_epoch_ms` / `epoch_ms_to_iso` / `days_from_civil` / `civil_from_days`，**纯整数**；测试用 `datetime` 对**全量 fixture 行**交叉断言（手写算法必须被标准库证伪过一次），边界含：闰日、月末/年末、`Z` 与 `±HH:MM` 偏移、小数秒、无偏移按声明时区。
2. `csvio.py`（K9）：`load_series` + `ERROR_CODES` 7 个错误码；列名同义词白名单 + 歧义即报错（不猜）；错误**带源行号、一次性收集统一报出**；缺失值 → `None`（**不补 0 不插值**）。
3. `profile.py`：`build_profile` + `cmd_profile` → `profile.json`（节奏/缺口/零值段/缺失段/重复时间戳/非单调）；**双跑 byte-identical** 断言。
4. `tools/gen_synthetic_series.py`（K11）：splitmix64 自研 RNG（**禁 stdlib random**）+ 场景"冷链仓储温控与能耗监测（虚构）"、3 个 `series_id` × 各 ~1000 点；植入四类异常各 ≥2 段、窗口边界段、`max_gap_ms` 两侧的相邻段对、重复/并列时间戳、缺口与零值段；产出 `data/synthetic/series.csv` + `manifest.json`（参数 + 逐文件 sha256）+ `data/truth/truth.json`（**只存输入与期望，禁 `observed`**）+ `data/truth/hash.txt`；`--check` 位级一致 + 篡改/缺失冻结产物 exit 2；生成器自身断言真值非平凡。
5. `data/samples/minimal.csv`（手写 ≤20 行，可人眼核对）。
6. 测试：`test_timebase.py` / `test_csvio.py` / `test_profile.py` / `test_generator.py`（冻结产物形态 + 重生成比对**两层**）。
7. **K1 退役第一步（同一提交内五处同步）**：`profile` 落地 → `STAGE_NOT_READY` 删 `profile` 键 → CLI 接线真实现 → 测试（`tests/test_skeleton.py` 的 `_ARGS_BY_COMMAND`/`_INPUT_FILES` 保持不变，not-ready 用例自动 skip；新增 `test_profile.py` 覆盖真实行为）→ 文档退出码表/README 当前状态表更新 → 决策记录补一条；**CI 同提交补一条 `profile` 离线冒烟步骤**（每条已交付命令都要有一条 CI 冒烟，且旧的就绪断言必须同时退役）。
8. 收尾：DoD 验证 → `plan/00·05·06` 状态回写 → 写 `plan/HANDOFF-M2.md` → commit。

## 3. 既定口径清单（K，动了会打挂测试）

- **K1 退出码契约（D8）**：0 成功 / 1 门禁或自检发现缺陷 / 2 用法与输入错误 / 3 阶段未就绪（骨架期） / 4 环境前提不满足。模块落地时对应键**整项退役**，五处同步（常量 → CLI 接线 → 测试 → 文档 → 决策记录）；`STAGE_NOT_READY` 空后删除 `EXIT_NOT_READY` 常量。
- **K2 序列化冻结**：JSON 落盘 `json.dumps(sort_keys=True, ensure_ascii=False, indent=2)` + LF + 结尾换行；HTML LF/UTF-8 无 BOM；**产物里禁时钟字段**；同输入双跑逐字节一致（冻结产物形态 + 重生成比对两层）。
- **K3 规范 JSON 只含整数与字符串**：浮点在哈希边界定点化（半偶舍入，`quant_decimals` 默认 6）；十进制展示串由整数构造；**禁浮点格式化参与哈希**（口径见 `data/README.md` §4.3）。
- **K4 数值可镜像**：哈希路径只允许 `+ - * / floor ceil abs min max` 与比较；幂次展开为连乘；**禁一切超越函数与库归约函数**（`exp/log/pow/sin/cos/sqrt`、`np.mean/sum`、`statistics.mean/median`）。M2 要为此加源码扫描门（Python AST + JS 词法）+ 变异验证。
- **K5 时间口径**：UTC **整数 epoch 毫秒**；落盘 ISO 定点串 `YYYY-MM-DDTHH:MM:SS.mmmZ` 由整数反算；不使用本地时区库；无偏移输入按 run-spec 声明时区解释并记录。
- **K6 排序与 tie-break**：所有排序给**全序比较器**（含源行号 index tie-break），禁止依赖引擎稳定性；Episode 严重度键 = `peak_score_q` 降 → `duration_ms` 降 → `start_row` 升 → `detector` 字典序；`episode_id = "<series_id>-E<NNN>"`。
- **K7 Episode 合并**：时间域 `max_gap_ms`（整数毫秒）；相邻异常点时间差 ≤ 该值即合并（**不跨数据缺口合并**）。
- **K8 参数面与生效值**：`run.json` 记录**解析后的最终值**（含 ACF 估出的 `period_points`、`max_gap_ms`、`quant_decimals`、算法/规范版本）；复算侧消费生效值、不重跑估计；**引擎里不留隐形默认**。
- **K9 数据契约与错误码**：`csvio.ERROR_CODES` 单点定义（`E_EMPTY_FILE`/`E_MISSING_COLUMN`/`E_DUPLICATE_COLUMN`/`E_TS_UNPARSEABLE`/`E_VALUE_UNPARSEABLE`/`E_DUPLICATE_TIMESTAMP`/`E_NON_MONOTONIC`）；每个错误带源行号或列名；一次报全部；归 exit 2。
- **K10 编码守卫**：`cli.py` 与 `tools/` 下**每个**可执行入口挂 `_ensure_utf8_stdio()`（新增脚本必须补挂，漏挂会让 windows CI 崩在 print 上）；子进程读写显式 `encoding=`；CI env `PYTHONUTF8=1`。
- **K11 生成器纪律**：splitmix64 自研 RNG（禁 `random`）；seed 显式传参并写入 manifest；`--check` 位级一致两层断言；**真值只存输入与期望、禁 `observed` 字段**；对账单元"自带结论"（不写恒为哑值的 `status` 字段）。
- **K12 零外链**：`assert_no_external_resources(html)` 在 `render` 出口**常驻**（禁 `http://`/`https://`/协议相对 `//`/`<link>`/`<script src>`），非仅测试期验一次。
- **K13 品牌隔离**：不冒用第三方库商标；比较性表述仅作事实引用；仓库名/Skill 名不含第三方品牌词。
- **K14 数字白名单**：报告中的每个数字必须命中 `facts.json` 的 `fact_id`，未命中 → exit 1 且不生成报告；叙事里的 `episode_id` 引用必须能在 `anomalies.json` 解析到。
- **K15 不留桩（D14）**：未落地模块**不产** `NotImplementedError`/`pass`/`return 0` 桩，"未就绪"只由 exit 3 表达；`tests/test_skeleton.py::TestNoSentinelStubs` 常驻扫描 `src/`+`tools/`（带正向对照与变异用例）；里程碑收尾人工再扫一遍。
- **K16 命令注册表三处同步**：`cli.COMMANDS` / `cli.STAGE_NOT_READY` / 测试侧 `_ARGS_BY_COMMAND` + `_INPUT_FILES`。**新增子命令必须同时补这三处**，否则 `TestCommandRegistryConsistency` 直接红。

## 4. 本机环境坑（只写实测过的）

- 用 `py` 不是 `python`（后者是商店占位符）；一律 `py -X utf8`。本机有 **3.8.8 与 3.12.10 两条通道**（`py -0p` 实测），每棒双解释器全量跑；**跨版本差异只能靠 CI**，别把"本机能跑"当跨版本证据。
- 全程 `PYTHONDONTWRITEBYTECODE=1`（含 pip 安装），源模式跑测：`PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 py -3.8 -X utf8 -m pytest tests/ -q`。
- pip 装包必须 `NO_PROXY="*" no_proxy="*"` + 清华镜像（本机系统代理会污染 pip）；本轮 `py -3.12 -m venv .venv-verify` + `pip install -e .` 一次成功（venv 建完即可用，未踩 ensurepip 坑）。**验证用 venv 用完立刻删**（本轮 `.venv-verify`/`.smoke` 已删，`git status` 干净）。
- Git Bash 的 `/tmp` 与 Windows 原生 Python 不通：临时文件用仓库内相对目录（本轮用 `.smoke/`，用完删）或系统临时目录。
- argparse 未知子命令抛 **`SystemExit(2)`**（不是返回值）：测试用 `pytest.raises(SystemExit)` 断 `.code == 2`。
- 变异脚本必须三连断言（替换前 marker 唯一存在 → 替换后字节已变 → 还原后字节一致），否则"测试仍绿"可能只是**没改到代码**；脚本文件用 `.tmp` 后缀（`.gitignore` 已忽略 `*.tmp`），验证完删除不入库。
- 默认分支 `main`，git 身份 `yuluo554 <282769740+yuluo554@users.noreply.github.com>`；`gh` 已登录 `yuluo554`（scopes 含 repo）。

## 5. DoD 逐项 checklist（M0 出口）

- [x] `plan/02–06` 五份计划文档落盘，待定决策表 P1–P6 记录推荐默认（用户未答复 → 按推荐默认执行，已声明）
- [x] 目录结构 + `pyproject.toml`（零运行时依赖、dev extra 仅 pytest、console script `anomaly-atlas`）+ `.gitattributes` + `.gitignore`
- [x] CI 预置 workflow（四矩阵 + `PYTHONUTF8=1` + 模块/裸命令两种形态冒烟）
- [x] CLI 退出码契约锁进测试（31 项，双解释器 + 干净 venv 三处全绿）
- [x] 退出码冒烟矩阵 14 条逐条实测（含"零副作用：不写假产物"）
- [x] 变异验证 4/4 变红（哨兵串门 / 编码守卫 / 输入前置检查 / not-ready 契约）
- [x] 哨兵串扫描 0 命中，且扫描器自带正向对照 + 注入用例
- [x] 安装面实测：editable 安装 + 裸 console script + `VERSION` 与 `pyproject` 一致性断言
- [x] `README.md` 诚实标注"M0 骨架阶段"（只列今天真能跑的命令，计划形态的命令明确标注未落地）+ `LICENSE`（MIT，防 M6 许可缺口）
- [x] `plan/HANDOFF-M1.md`（本文档）六节齐落盘并 commit
- [ ] CI 首推全绿 —— **未接远端，待 M6 首推验证**（不可本机实跑；ubuntu 腿与 CI 步骤形态是本地等价校验的缺口）

## 6. 关键命令速查

```bash
cd <repo>
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1

py -3.8  -X utf8 -m pytest tests/ -q          # 全量测试（3.12 同）
py -3.12 -X utf8 -m pytest tests/ -q
py -3.8  -X utf8 -m anomaly_atlas.cli --help     # exit 0
py -3.8  -X utf8 -m anomaly_atlas.cli --version  # exit 0
py -3.8  -X utf8 -m anomaly_atlas.cli profile data/synthetic/series.csv   # M1 落地后；此前 exit 3

# 安装跑法（本机实测一次成功；验证完删 venv）
py -3.12 -m venv .venv-verify
NO_PROXY="*" no_proxy="*" ./.venv-verify/Scripts/python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv-verify/Scripts/anomaly-atlas.exe --help
```
