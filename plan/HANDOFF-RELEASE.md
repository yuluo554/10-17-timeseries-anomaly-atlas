# HANDOFF-RELEASE（M6 已收尾 → 发布版 v0.1.0）

> 用法：新对话 `/goal 读取 <项目绝对路径>\plan\HANDOFF-RELEASE.md 继续完成任务`（库内一律相对路径）。
> 这是收束棒：M1–M6 全部落地并已发布。下一棒没有既定任务，先读 §2 再决定。

## 1. 当前进度 + 证据（全部本轮实测）

- **发布完成**：仓库 <https://github.com/yuluo554/10-17-timeseries-anomaly-atlas>（public，`main` 为默认分支），tag `v0.1.0`（annotated 对象 `5ad560a507b91b839a919ab2439ea02fd665208b` → commit `da2a9c20a00f14b56a0ffd0ed2f4b76907a12952`），Release 五个附件。留档：[`plan/RELEASE-M6.md`](RELEASE-M6.md)。
- **CI 四矩阵全绿**：windows/ubuntu × 3.8/3.12。`main` 与 tag 的 push 各一 run，均 4/4 success。
- **CI 对账**：截至发布动作结束共 6 条 push 事件 ↔ 6 条 run，`head_sha` 全部对上（逐条见 RELEASE-M6 §2，第 1 条是首推失败，其余全绿）。
  - 对账表之后的文档提交也按同一判据单独核对过：`5751434` → run 39089535330 success、`d2b15cd` → run 39089756812 success、`99d0d0c` → run 39089997417 success，均四矩阵全绿。
  - **承载对账表的提交本身不进表**（写进去就又要再提交一次，永远差一条）；收录口径写在 RELEASE-M6 §2 的"截止点与元事件"。跟随这条口径的人只需核对"一事件一 run + `head_sha` 相同 + 四矩阵全绿"——这一判据对任何后续提交都适用。
  - 首推 `2239f3e` **红过**：workflow YAML 里 5 处 step `name` 含裸 `: `，GitHub 判定文件非法、**一个 job 都没派发**。修复提交 `da2a9c2` 加引号后复验。这是 HANDOFF-M6 §1 那条"CI 新步骤未实跑"缺口的真实兑现。
- **发布物本体已验**（全部在仓库外目录）：
  - `gh release download v0.1.0 -D .tmp/rel` → 5 附件 sha256 与本地逐条相同（`atlas.html` `9de5a102…` / `series.csv` `4e644ff2…` / `manifest.json` `9a47138a…` / `truth.json` `0ef1169b…` / `hash.txt` `50c4de14…`）。
  - `verify .tmp/rel/atlas.html` → **exit 0 / VERIFIED**（`6020a3d3…`）。
  - 下载的 CSV 重跑 `detect` → 同一指纹 + `facts.json` 1861 条事实。
  - `git clone --branch v0.1.0` 到 `.tmp/clone2` → `selftest` 6 检查 0 失败、`verify` exit 0、生成器 `--check` 逐字节、全量 **603 passed**。
- **快照编码**：`git archive v0.1.0` 与真 clone 各 61 个文件，无 CRLF、无 BOM、严格 UTF-8 可解码。
- **本机双解释器**（发布前）：3.12 `603 passed` / 3.8 `603 passed`。
- **冻结资产零改动**：`data/`、`examples/atlas.html`、`tests/` 内容未改；本轮代码侧唯一改动是 `.github/workflows/ci.yml` 的 5 处引号。
- **版本一致**：`pyproject.toml` 0.1.0 == `anomaly_atlas.VERSION` 0.1.0 == tag `v0.1.0`。

## 2. 下一棒可选（没有既定任务；按需取一）

1. **什么都不做**：发布版已闭环。若要长期维护，最值得做的是把 CI 的 action 版本升上去（`actions/checkout@v4` / `actions/setup-python@v5` 仍声明 Node 20，runner 已强制在 Node 24 上跑），并在 `ubuntu-latest` 于 2026-10-19 迁到 Ubuntu 26 之后重跑一次四矩阵确认。
2. **发布 0.1.1（只改文档/CI 时）**：走一遍 `py -3.12` / `py -3.8` 全量 + `tools/gen_synthetic_series.py --check` + `verify examples/atlas.html`，再 tag。
3. **扩展功能**（题面边界之外）：先读 `plan/06` §2「边界与非目标」——token replay / 实时流式 / 深度学习检测器只进 roadmap。要动检测算术，先看下面 K4/K18。

## 3. 既定口径清单（K，动了会打挂测试）

M1–M5 的 K1–K32 原样有效，见 [`HANDOFF-M6.md`](HANDOFF-M6.md) §3。发布轮新增：

- **K33 发布物身份 = tag 对象 + 附件 sha256，不是"指向同一个 commit"**：远端 tag 对象必须与本地逐字节一致（本轮用 `git mktag` 按远端原始字节重建 `5ad560a5…`）。
- **K34 CI 的 step `name` 一律加引号**：值里含 `: `、`#`、`{`、`}` 时 YAML 会歧义。改完先在本地 `yaml.safe_load` 解析，再推。
- **K35 CI 对账按"ref 写入事件"记账**：一次 `git push` 可能产生多于一个 run（本轮 tag ref 写过两次 → 两个 run）。对账表必须与 `gh api .../actions/runs` 的事实一一对应，不合并。
- **K36 发布物验证必须离开工作区**：附件用 `gh release download`、快照用真 `git clone --branch <tag>`。在源目录里 `verify` 自己的产物不构成发布验证。
- **K37 发布后冻结资产零改动**：`data/`、`examples/atlas.html`、`tests/` 不动内容；要改就得重跑生成器 `--check` + 三处全绿 + 重新发版。

## 4. 本机环境坑（M6 新增，其余见 HANDOFF-M6 §4）

- **`github.com:443` 间歇性不通、`api.github.com` 正常**（本轮实测：`gh` 全程可用，`git push`/`clone`/`ls-remote` 反复超时）。绕过：
  ```bash
  git -c http.curloptResolve=github.com:443:20.205.243.166 <clone|push|ls-remote> ...
  ```
  注意 `curl` 直接访问 `https://github.com/` 可能照样超时，但带 `--resolve` 稳定 200——说明是 DNS 解析到的那个 IP 被限，不是整个域不可达。
- **`gh` 建 tag 的时区**：API 建 tag 对象会按给定日期写入；远端返回统一显示为 `Z`。要与本地对象对齐，用 `git mktag` 按远端返回的 `tagger` 字段拼原始字节（时区部分按你提交时的偏移，本轮是 `+0800`）。
- **`gh api ... -f tagger='{...}'` 不工作**：嵌套对象必须走 `--input <json file>`。
- **`git push origin v0.1.0` 超时后不要慌**：用 API 建 ref 一样能触发 CI；`gh release create` 走 uploads API，不受 git 传输影响。
- 其余（`py -X utf8`、`.tmp/` 临时目录、venv 用完即删、IAB 不支持 `file:`）见 HANDOFF-M6 §4。

## 5. DoD 逐项 checklist（M6 出口，全部已勾）

- [x] 建仓（public，账号 `yuluo554`）+ 首推，**CI 四矩阵全绿**（首推红过一次，修复后全绿）
- [x] 每个 push/tag 事件恰一次 CI run 且 `head_sha` 全对上的对账表（`plan/RELEASE-M6.md` §2）
- [x] `git tag v0.1.0`（版本与 `pyproject.toml`/`VERSION` 一致）+ GitHub Release（HTML + 四份基准数据）
- [x] `plan/RELEASE-M6.md` 留档（tag / Release URL / 产物 sha256 / CI 对账表 / 已知环境问题）
- [x] **发布物本体已验**：下载附件 → `verify` exit 0 / VERIFIED；sha256 一致；clone 后 `selftest` 6/6
- [x] `plan/00·02·05·06` 状态回写（M6 行）+ README 同步 + commit
- [x] 发布后**冻结资产零改动**

## 6. 关键命令速查

```bash
cd <repo>
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1

# 全量测试（发布前双解释器各跑一次）
py -3.12 -X utf8 -m pytest tests/ -q
py -3.8  -X utf8 -m pytest tests/ -q

# 发布物复核（可随时重跑）
gh release download v0.1.0 -D .tmp/rel && sha256sum .tmp/rel/*
py -3.12 -X utf8 -m anomaly_atlas.cli verify .tmp/rel/atlas.html
git -c http.curloptResolve=github.com:443:20.205.243.166 clone --branch v0.1.0 \
  https://github.com/yuluo554/10-17-timeseries-anomaly-atlas.git .tmp/clone2
cd .tmp/clone2 && PYTHONPATH="$PWD/src" python -X utf8 -m anomaly_atlas.cli selftest && cd -

# CI 对账（事件 ↔ run）
gh api "repos/yuluo554/10-17-timeseries-anomaly-atlas/actions/runs?per_page=50" \
  --jq '.workflow_runs[] | "\(.id) \(.event) \(.head_branch) \(.head_sha[0:7]) \(.conclusion)"'

# CI 校验（改 workflow 后必做）
py -3.12 -X utf8 -c "import yaml;d=yaml.safe_load(open('.github/workflows/ci.yml',encoding='utf-8'));print(len(d['jobs']['test']['steps']),'steps ok')"
```
