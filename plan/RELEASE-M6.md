# RELEASE-M6 发布留档（v0.1.0）

> 本文件是 M6 的出口证据，不是计划。每个数字都来自本轮实测；核对方式是重新跑一遍下面列出的命令。
> 仓库：<https://github.com/yuluo554/10-17-timeseries-anomaly-atlas>（**public**）

## 1. 发布三件套

| 项 | 值 |
| --- | --- |
| tag | `v0.1.0`（annotated tag 对象 `5ad560a507b91b839a919ab2439ea02fd665208b`，指向 commit `da2a9c20a00f14b56a0ffd0ed2f4b76907a12952`） |
| Release | <https://github.com/yuluo554/10-17-timeseries-anomaly-atlas/releases/tag/v0.1.0>（id `RE_kwDOVN772M4YzmpL`，2026-10-18T01:49:18Z，非 draft / 非 prerelease） |
| 版本一致性 | `pyproject.toml: version = "0.1.0"` == `anomaly_atlas.VERSION = "0.1.0"` == tag `v0.1.0`（`tests/test_skeleton.py::TestVersionConsistency` 常驻钉住） |
| tag 覆盖范围（口径） | tag 指向 `da2a9c2`（发布代码 + CI 修复）。其后的提交只改 `plan/` 与 `README.md`（留档与状态回写），**不改 `src/`、`data/`、`examples/`、`tests/`**——所以 tag 快照的代码与冻结资产与 `main` 尖端逐字节相同，只是少了文档。若要让 tag 也覆盖留档，需重新打 tag 并重发 Release，本轮刻意不做（发布件一旦发出就不再移动）。 |

### Release 附件（GitHub 侧 digest 与本地 sha256 双向对账）

| 附件 | 字节 | sha256 |
| --- | --- | --- |
| `atlas.html` | 832179 | `9de5a102f3d056e997421b19f9ef93ebd193c2b7c8cef6527415fbbf712dc1a1` |
| `series.csv` | 127131 | `4e644ff21920b8e03ea91f18970ae8e327c0663c0ee7b2c210cd36c7f5f4b612` |
| `manifest.json` | 3257 | `9a47138ad46358e4e1ea15a2f33c2297b07256e5a880526fab2707ef90a2ec37` |
| `truth.json` | 18723 | `0ef1169b2af24a84c90d06dabf6482eadf655e406f054522521a6e9024cd9965` |
| `hash.txt` | 65 | `50c4de142294d5af97acab7b5b7d34ec8e4955886259128a248ac19892a46e51` |

- 二进制本体未改：`atlas.html` 由 `render data/synthetic/series.csv` 重建后与仓库内 `examples/atlas.html` **逐字节相同**（上传前实测，832179 B）。
- `hash.txt` 内容是 `truth.json` 的冻结校验值：`ad3822a14c95dd3478eeea1c58090bc1cd1afd0eea3f82aed91588a9f0b75d5c`。
- 异常集指纹（默认 spec）：`6020a3d34b0228c9b0735d7b2d10aad67d3181d0cb02eb2a02d7fd864ef1b422`（178 episodes / 653 detections / 3 series）。
- `pad_rows=6`、`heat_bin_ms=3600000` 是**呈现参数**，走 render 自己的 run-spec，不进 `run.json`、不进指纹（K8 / D22）。

## 2. CI 对账表（push / tag 事件 → run → 结论）

核对方式：`gh api repos/yuluo554/10-17-timeseries-anomaly-atlas/actions/runs?per_page=50`，逐条比对事件的 `head_sha` 与 run 的 `head_sha`。

| # | 事件 | ref | head_sha | run id | run 的 head_sha | 四矩阵 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | push | `refs/heads/main` | `2239f3e` | 39087513068 | `2239f3e` | **0 job**（工作流本身未被解析） | ❌ failure（见 §3） |
| 2 | push | `refs/heads/main` | `da2a9c2` | 39087657970 | `da2a9c2` | windows/ubuntu × 3.8/3.12 全 success | ✅ success |
| 3 | push | `refs/tags/v0.1.0`（第 1 次建 ref，lightweight 指向 commit） | `da2a9c2` | 39087971984 | `da2a9c2` | windows/ubuntu × 3.8/3.12 全 success | ✅ success |
| 4 | push | `refs/tags/v0.1.0`（删掉重建，改指 annotated tag 对象 `5ad560a5`） | `da2a9c2` | 39088141703 | `da2a9c2` | windows/ubuntu × 3.8/3.12 全 success | ✅ success |
| 5 | push | `refs/heads/main`（M6 留档与状态回写） | `5751434` | 39089535330 | `5751434` | windows/ubuntu × 3.8/3.12 全 success | ✅ success |
| 6 | push | `refs/heads/main`（对账表补记） | `d2b15cd` | 39089756812 | `d2b15cd` | windows/ubuntu × 3.8/3.12 全 success | ✅ success |
| 7 | push | `refs/heads/main`（对账收录口径） | `99d0d0c` | 39089997417 | `99d0d0c` | windows/ubuntu × 3.8/3.12 全 success | ✅ success |
| 8 | push | `refs/heads/main`（HANDOFF 末次核对） | `9aa1fef` | 39090510615 | `9aa1fef` | windows/ubuntu × 3.8/3.12 全 success | ✅ success |
| 9 | push | `refs/heads/main`（tag 覆盖范围口径） | `e418494` | 39090721055 | `e418494` | windows/ubuntu × 3.8/3.12 全 success | ✅ success |
| 10 | push | `refs/heads/main`（对账表补至 9 条） | `189f716` | 39091350257 | `189f716` | windows/ubuntu × 3.8/3.12 全 success | ✅ success |

- **快照口径**：上表是截至快照提交 `189f716` 的**完整事件列表（共 10 条）**，与 `gh api .../actions/runs` 的 `total_count` 逐条对应，无遗漏、无合并、无推测；每个 run 的 `head_sha` 都等于对应事件的 sha。
- **为什么不再往下追加**：本文件自身的任何一次提交也会产生一个 push 事件；把它写进表又要再提交一次，永远差一条。因此本表是**快照**，不是实时总数。快照之后的提交（只改 `plan/` 或 `README.md`）按同一判据核对——"一事件恰一 run + `head_sha` 相同 + 四矩阵全绿"——核对结果记在 `plan/HANDOFF-RELEASE.md`，不追加入表。
- 第 1 条是首推，红了——原因不是代码，是工作流 YAML 本身（详见 §3）。这正是 HANDOFF-M6 §1「CI 本轮新增的 5 步 M5 冒烟均未实跑」所留的缺口，首推把它暴露出来了。
- 第 3/4 条是 tag ref 的**两次真实写入**：本机 `git push` 因连接超时无法完成，改由 API 建 ref；第一次建的是 lightweight ref，随后为满足"annotated tag"口径删掉重建为指向 tag 对象的 ref。两次写入各触发一个 run，都绿——按"每个 ref 写入事件恰一次 run"记账，两条各自成立。
- 第 5–10 条是 M6 收尾的**纯文档提交**（`5751434` → `189f716`），四矩阵同样全绿，说明文档改动没有碰到任何门禁。
- 表中 `head_sha` 是 tag 事件解引用后的 commit sha；tag 对象本身是 `5ad560a507b91b839a919ab2439ea02fd665208b`。
- 各 job 的矩阵腿与耗时（第 2 条）：windows/3.8、ubuntu/3.8、ubuntu/3.12 均约 2 分钟，windows/3.12 约 2 分 45 秒。

## 3. 首推失败与修复（实测记录）

首推 `2239f3e` 的 run 只有一个 job 都不存在的"failure"——GitHub 判定工作流文件不合法，没有派发任何 job：

- 根因：`.github/workflows/ci.yml` 里 5 个 step 的 `name:` 用了不带引号的标量，值里含 `: `（如 `name: CLI smoke (selftest: ledger + ...)`）。YAML 把第二个冒号当成 mapping 分隔符，整个文件解析失败。
- 本地等价校验漏掉它的原因：此前只跑过 `pytest` 与命令本身，**从未对 workflow 做 YAML 解析**。
- 修复：`da2a9c2` 给这 5 处 `name` 加双引号，并在本地用 `yaml.safe_load` 解析一遍（26 个 step、四矩阵、`on: [push, pull_request, workflow_dispatch]` 全部读出）。
- 修复后：`main` 与 `tag` 两次 push 的四矩阵全绿（表 §2 第 2–4 行）。此后每一次文档提交（第 5–9 行）也都全绿。

## 4. 发布物本体已验（真下载 + 中立目录）

全部在**仓库外的目录**里做，避免"从自己的工作区读文件"这种假证据：

| 验证 | 命令 / 方法 | 结果 |
| --- | --- | --- |
| 附件下载 | `gh release download v0.1.0 -D .tmp/rel` | 5 个文件齐全，sha256 与 §1 表逐条相同 |
| 下载的 HTML 复算 | `anomaly_atlas.cli verify .tmp/rel/atlas.html` | **exit 0 / VERIFIED**，复算 `6020a3d3…` == 构建 `6020a3d3…` |
| 下载的 CSV 重跑检测 | `detect .tmp/rel/series.csv --out-dir .tmp/rel/out` | `6020a3d3…`（与仓库产物相同），`facts.json` 1861 条事实 |
| tag 快照 | `git clone --branch v0.1.0`（真实 clone，非 tarball） | commit `da2a9c2`，`git describe --tags` = `v0.1.0` |
| clone 后 `selftest` | 在 clone 目录内 `-m anomaly_atlas.cli selftest` | **6 检查 0 失败 / 6 探针全过，exit 0** |
| clone 后 `verify` | `verify examples/atlas.html` | exit 0 / VERIFIED（`6020a3d3…`） |
| clone 后生成器 `--check` | `tools/gen_synthetic_series.py --check` | 4 份冻结产物与 manifest 台账一致且逐字节重生成 |
| clone 后全量测试 | `pytest tests/ -q`（3.12，源码模式） | **603 passed** |

## 5. 快照编码纪律复核

- `git archive v0.1.0` 解出的全部跟踪文件（当时 61 个；以 `git ls-files` 的全量为准，不写死数字）：无 CRLF、无 BOM、全部可严格 UTF-8 解码。
- 真实 clone（`git clone --branch v0.1.0`）后对同一批文件复查：结果相同。
- `.gitattributes` 的 `* text=auto eol=lf` 在 clone 上生效，`data/synthetic/manifest.json` 的 sha256 台账在 clone 里仍然成立（`--check` 已证）。
- 这两个检查覆盖的正是 `data/README.md` §5 冻结纪律所依赖的前提。**该声明现已由门禁覆盖**：`tests/test_skeleton.py::TestSnapshotEncoding` 扫 `git archive HEAD` 的快照字节（无 CR/BOM、严格 UTF-8），带扫描面自证与"注入 CR/BOM/非法字节必红"的变异探针。

## 6. 已知环境问题摘要

1. **首推 CI 红过一次**（工作流 YAML 非法，见 §3）。已修，修复提交 `da2a9c2` 同时是 tag 指向的 commit。**教训**：CI 的"本地等价校验"必须包含对 workflow 文件本身的 YAML 解析，否则第一次真实推送就是第一次校验。
2. **本机 git 通道间歇性不通**（`github.com:443` 超时，`api.github.com` 正常）。绕过方式：`git -c http.curloptResolve=github.com:443:20.205.243.166 <command>`；`gh` 子命令不受影响。发布期间 tag ref、Release、附件上传与下载均已完成，未留下未完成步骤。
3. **tag 对象在两端逐字节一致**：本地先按 `+0000` 建了一版 annotated tag（`ba368e3c…`），与远端 API 建出的对象不同哈希；随后把远端返回的字段还原成原始对象字节（tagger 时间 `1792288158 +0800`）用 `git mktag` 重建，得到同一个 `5ad560a507b91b839a919ab2439ea02fd665208b`，`git ls-remote` 与本地 `git rev-parse` 现在相同。这个还原同时验证了"GitHub 存的就是 tagger 时间戳的秒级 epoch + 时区"这一判断。
4. **Node 前提**：`verify` 需要本机 Node（缺失时 exit 4 + 两条补救路径，不静默跳过）。GitHub runner 预装 Node，CI 里有显式 `node --version` 步骤。
5. **`selftest` 的 exit 4**：源码/editable 安装下 `_PACKAGE_ROOT` 指向仓库根，命令行无法触发"找不到冻结数据"分支；由单测 monkeypatch 覆盖（与 M5 记录一致）。
6. **数字白名单是值级门禁**：恰好等于某条台账事实的编造数字能过，保证"有出处"而非"用得对"（K31）。Release 说明与 README/SKILL.md 都按这个口径写。
7. **CI 的平台告警**（非失败）：`actions/checkout@v4`、`actions/setup-python@v5` 仍声明 Node 20，runner 强制在 Node 24 上跑；`ubuntu-latest` 将于 2026-10-19 起迁移到 Ubuntu 26。两条都不影响本次结论，但下次改 CI 时应顺手升 action 版本。

## 7. 冻结资产零改动

发布前后 `data/`、`examples/atlas.html`、`tests/` 未做任何内容修改；本轮唯一改动的仓库文件是 `.github/workflows/ci.yml`（首推修复），另有 `plan/RELEASE-M6.md` 与 `plan/00·02·05·06` 的状态回写。

复核命令：

```bash
sha256sum examples/atlas.html data/synthetic/series.csv data/truth/truth.json
# 9de5a102… / 4e644ff2… / 0ef1169b…（与 §1 表一致）
py -3.12 -X utf8 tools/gen_synthetic_series.py --check
```
