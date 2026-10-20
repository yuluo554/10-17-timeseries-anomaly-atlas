# RELEASE-0.1.1 发布留档（v0.1.1 维护版）

> 本文件是 0.1.1 维护轮的出口证据，不是计划。数字全部来自本轮实测（2026-10-20）；核对方式 = 重跑下面列出的命令。
> 上一版（首发）留档见 [`RELEASE-M6.md`](RELEASE-M6.md)。
> **自指纪律**：本文件在 tag 之前写定，因此**不写** Release id、上传时间与 tag 指向的 commit sha
> （那些值在写入引用自己的那一版之后就不再成立）；它们写在 GitHub Release 页面与 annotated tag 消息里。

## 1. 发布三件套

| 项 | 值 |
| --- | --- |
| tag | `v0.1.1`（annotated；指向本轮维护提交的尖端） |
| Release | <https://github.com/yuluo554/10-17-timeseries-anomaly-atlas/releases/tag/v0.1.1>（id / 上传时间见页面） |
| 版本一致性 | `pyproject.toml: version = "0.1.1"` == `anomaly_atlas.VERSION = "0.1.1"` == tag `v0.1.1`（`tests/test_skeleton.py::TestVersionConsistency` 常驻钉住） |
| tag 覆盖口径 | tag 就是尖端：`git rev-list --count v0.1.1..HEAD` = **0**（**没有** v0.1.0 那种"tag 落后 9 个提交"的缺口） |
| `v0.1.0` | 原样保留：tag、Release、五个附件**均未移动、未删除** |

### Release 附件（5 个，与 v0.1.0 逐字节相同）

产物是确定性的（`tools/mirror_parity.py --build` 重建出来与新 tag 树里的 `examples/atlas.html` 逐字节相同），
所以 v0.1.1 沿用同一批附件，字节数与 sha256 与 v0.1.0 一致：

| 附件 | 字节 | sha256 |
| --- | --- | --- |
| `atlas.html` | 832179 | `9de5a102f3d056e997421b19f9ef93ebd193c2b7c8cef6527415fbbf712dc1a1` |
| `series.csv` | 127131 | `4e644ff21920b8e03ea91f18970ae8e327c0663c0ee7b2c210cd36c7f5f4b612` |
| `manifest.json` | 3257 | `9a47138ad46358e4e1ea15a2f33c2297b07256e5a880526fab2707ef90a2ec37` |
| `truth.json` | 18723 | `0ef1169b2af24a84c90d06dabf6482eadf655e406f054522521a6e9024cd9965` |
| `hash.txt` | 65 | `50c4de142294d5af97acab7b5b7d34ec8e4955886259128a248ac19892a46e51` |

冻结指纹（未动）：异常集 `6020a3d34b0228c9b0735d7b2d10aad67d3181d0cb02eb2a02d7fd864ef1b422`、真值 `ad3822a1…`。

## 2. 本轮改了什么（相对 v0.1.0）

| 诊断项 | 变更 | 位置 |
| --- | --- | --- |
| D1 | 解释器下限 `>=3.8` → **`>=3.12`**，并补 `Programming Language :: Python :: 3.12` classifier | `pyproject.toml` |
| D1 | CI 矩阵 `{windows,ubuntu} × {"3.8","3.12"}` → **`{windows-latest, ubuntu-latest} × {"3.12"}`** | `.github/workflows/ci.yml` |
| D1 | README 源码直跑口径与「已知环境问题·解释器下限」写明 3.12 与各版本 EOL 日期 | `README.md`、`SKILL.md` |
| D2 | `actions/checkout@v4 → v7`、`actions/setup-python@v5 → v7` | `.github/workflows/ci.yml` |
| D3 | `license = { text = "MIT" }` → SPDX `license = "MIT"` + `license-files`；删 `License ::` classifier；`[build-system] requires` `setuptools>=61 → >=77` | `pyproject.toml` |
| D4 | **新增 `MANIFEST.in`**：sdist 纳入 `tests/`（含 `conftest.py`）、`tools/`、`data/`、`examples/` | `MANIFEST.in` |
| D5 | README「已知环境问题」补一条：`selftest` 需仓库内 `data/synthetic/`+`data/truth/`，中立 CWD 下 **exit 4**，其它子命令不受影响（不加退化路径） | `README.md` |
| D6 | **新增快照编码门** `TestSnapshotEncoding`：扫 `git archive HEAD` 快照字节（无 CR / 无 BOM / 严格 UTF-8），带扫描面自证与注入探针 | `tests/test_skeleton.py` |
| D6 | 两处「61 个文件」改为不写死数字，并注明该声明已有门禁 | `plan/RELEASE-M6.md`、`plan/HANDOFF-RELEASE.md` |
| D8 | `data/README.md` §1 补机读复核锚 `next_review: 2027-01-17`（只加锚，不动既有结论与数字） | `data/README.md` |
| D9 | `.gitignore` 加 `update/`（交接目录不入仓） | `.gitignore` |

## 3. 验收（每条附命令与实测结果）

| # | 命令 | 实测结果 |
| --- | --- | --- |
| 1 | 新 CI run（`push` 事件，commit `cbdf6af`） | run **`39363194431`**（2026-10-20T03:13:56Z）：`test (ubuntu-latest, 3.12)` + `test (windows-latest, 3.12)` **两腿全 success**；**注解 6 → 1** |
| 1b | 注解明细 | Node20 弃用 warning **4 → 0**；剩 **1 条** notice = GitHub 平台的「ubuntu-latest 将于 2026-10-19 起迁往 Ubuntu 26」。**实测该腿仍解析为 `ubuntu-24.04`（`24.04.5 LTS`，Image `ubuntu-24.04`）**，迁移尚未实际切换 → 这不是本仓配置造成的；清零只能靠钉镜像，而 DEC1=A 明确「不加镜像钉」，故**接受这 1 条**（用户 2026-10-20 拍板） |
| 2 | `py -3.12 -m pytest -q`（干净 venv，`pip install -e ".[dev]"`） | **606 passed**（改前 603；新增 3 项编码门用例），exit 0 |
| 3 | `python -m build --wheel --sdist`（`PYTHONDONTWRITEBYTECODE` 置空） | `grep -ci warning` = **0**（改前 4 + 8 条弃用 WARNING） |
| 3b | wheel `METADATA` | `License-Expression: MIT`、`Requires-Python: >=3.12`、`Classifier: ... :: 3.12`、**无** `License ::` |
| 4 | sdist 自足：解压树 → 干净 venv → `pip install -e ".[dev]"` → `pytest -q` | **606 passed**（与仓库**同一收集数**）；解压树内 `data/synthetic/series.csv` sha256 = `4e644ff2…`（台账成立） |
| 5 | `python -m anomaly_atlas.cli selftest` | `selftest: 6 check(s), 0 failing`，6 条 `[probe ok]`，exit 0（**未**新增第 7 项，编码门留在 pytest/CI 侧） |
| 6 | `python tools/gen_synthetic_series.py --check` | `4 frozen artifacts match the manifest ledger and regenerate bit-for-bit`，exit 0 |
| 7 | `python -m anomaly_atlas.cli detect data/synthetic/series.csv --out-dir <tmp>` | `6020a3d3…`（冻结指纹未动） |
| 8 | `python -m anomaly_atlas.cli verify examples/atlas.html` | `VERIFIED`（复算 == 构建 == `6020a3d3…`），exit 0 |
| 9 | `python tools/mirror_parity.py --build %TEMP%\atlas-v011.html` | sha256 `9de5a102…` **== `examples/atlas.html`**（确定性重建） |
| 10 | 负控（编码门） | 在临时 clone 里提交一个含 CR 的 blob（`probe.png`，被 `.gitattributes` 标为 `binary` 故 git 保留 CR）→ 门禁**变红并指名** `('probe.png', 'CR')` |
| 11 | `python -c "import yaml; yaml.safe_load(...ci.yml...)"` | `yaml ok`（本仓首推曾被 YAML 裸冒号坑红，改 CI 后先本地解析） |

## 4. 未做 / 未验证（不许当成 PASS）

| 项 | 状态 | 原因 |
| --- | --- | --- |
| 「注解 0 条」 | **未完全达成（6 → 1）** | 剩下的 1 条是平台的 ubuntu-latest 迁移 notice；清零需钉镜像，与 DEC1=A 相悖。用户已拍板接受 |
| `ubuntu-latest` 真正切到 Ubuntu 26 后本仓是否仍绿 | **未验证** | 本轮实测该标签仍是 24.04；迁移完成后的那次 run 才是真正的"新镜像"证据 |
| 浏览器通道目检（徽章、滑杆、打印） | **未重做** | 本轮未改产物字节（`9de5a102…` 不变），故只做了机器通道（`verify` / `mirror_parity`）；`examples/atlas.html` 断网可开这一条沿用 M3/M4 的浏览器实测 |
| 从 CRLF 工作树打 sdist | **已知会破台账** | `MANIFEST.in` 是"随包带走"；setuptools 读取工作树字节，若工作树是 CRLF 则解压树里的 `manifest.json` 台账不成立。本机工作树已归位为 LF，且编码门钉的是 `git archive` 快照 |
| `plan/HANDOFF-M*.md` 里的 3.8/双解释器读数 | **未改** | 属既往读数的历史记录，本轮只允许补注（未补） |
