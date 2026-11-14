# AGENTS.md：给 AI 助手的项目说明

这份文件写给要阅读、修改或调用本项目的 AI 模型（Claude、GPT/Codex、Gemini、DeepSeek 等）。面向人类用户的说明在 `README.md`。

## 1. 这是什么

Hub 是一个本机多 Agent 调度器：把同一台 Mac 上已登录的几个 AI 命令行工具组织成一个「小公司」，让它们互相派活、并行协作、互相审查，并提供一个本地网页面板展示全过程。

- 不调用任何云端 API 密钥做推理，只调用各家**官方命令行客户端**，复用它们已有的登录状态。
- 默认只读；只有显式传 `--write`（或面板勾选「允许改文件」）时成员才能改文件。
- 只用 Python 标准库，兼容 Python 3.9，没有第三方依赖。

## 2. 目录结构

| 路径 | 作用 |
| :--- | :--- |
| `hub` | 全部后端逻辑，单文件 Python 脚本（约 3300 行）：命令行、各后端适配、排工/执行/汇总、会审、对接人、额度读取、面板 HTTP 服务、局域网配对、纯标准库二维码。 |
| `ui.html` | 面板前端，单文件原生 JavaScript + CSS，没有构建步骤。由 `hub ui` 的 HTTP 服务直接下发。 |
| `app/` | macOS 原生窗口壳（Swift + WKWebView），只负责打开 `http://127.0.0.1:8765/`。`sh app/build.sh` 编译并安装到 `~/Applications/Hub.app`。 |
| `install.sh` | 先跑离线测试，通过后把 `hub` 装到 `~/.local/bin/hub`、`ui.html` 和 `README.md` 装到 `~/.agent-hub/`，并重启面板服务。旧版本备份到 `~/.agent-hub/backup/`。 |
| `tests/` | `smoke.sh` 是离线回归（不联网、不花额度，必须通过）；`live.sh` 会真实调用模型、花少量额度，平时不要跑。 |

**约定：`hub` 和 `ui.html` 保持单文件，不引入第三方库、不加构建工具。**

## 3. 成员与后端

成员（agent）是一个名字加一条「首选 → 备用」模型链，配置在 `config.json` 的 `agents` 里，每项写成 `"后端:模型"`：

| 后端 | 调用的命令 | 说明 |
| :--- | :--- | :--- |
| `agy:<model>` | Antigravity CLI `agy --print=<prompt> --output-format stream-json` | 只配置 `gemini-*` 模型。 |
| `codex[:<model>]` | `codex exec ... --json -`（提示词走 stdin） | 只读用 `-s read-only`；写模式用 `workspace-write`，配置 `gpt_full_access: true` 时用 `danger-full-access`。思考强度来自 `codex_effort`。 |
| `dsh` | DeepSeek Harness `dsh --patch <HUB_HOME>/dsh.patch.yml --profile headless --json -` | patch 让无界面模式复用桌面版已登录的账号，不复制密钥。 |
| `claude:<model>` | Claude Code `claude -p --model <m>`（提示词走 stdin） | 只读用 `--permission-mode plan`，写模式用 `acceptEdits`；调用前会清掉 `CLAUDE*`、`ANTHROPIC_*` 环境变量。 |

默认分工（写在提示词和 `profiles` 里）：Gemini 干执行类的活并默认负责排工和汇总；Claude、GPT 负责拍板和审查，画图只有 GPT 能做；DeepSeek 做零碎小活。

前一个模型失败（超时、未登录、额度用完）时，`ask()` 会按链顺序自动换下一个，记录里会标明实际用了哪个。

**思考等级**：配置 `effort` 是 `{成员: 档位}`，档位名沿用各模型自己的（`effort_levels(spec)`）：GPT 读 `~/.codex/models_cache.json` 里该模型的 `supported_reasoning_levels`，以 `-c model_reasoning_effort=…` 传入；Claude 是 `low/medium/high/xhigh/max`，以 `--effort` 传入；Gemini 的档位是不同的模型名（如 `gemini-4-carbon-high`），面板通过换模型来调；DeepSeek 不支持。模型不支持所选档位时不传。旧配置 `codex_effort` 只在成员没单独设过时作为 GPT 的后备。

**续接原生会话**：每次调用会把后端返回的会话编号存进记录的 `session`。追问时由 `resume_plan()` 判断能否直接续接：同一位成员、同一个模型、上一轮成功、没派过团队、不是分叉、上下文范围是完整、且那个会话还没被别的分支续过（`session_continued_by`）。能续接就只发这一轮的话（GPT `codex exec resume <id>`、Gemini `agy --conversation <id>`、Claude `claude --resume <id> --output-format json`、DeepSeek `dsh --session-id <id>`）；续接失败自动改为把前文写进提示词新开会话。

## 4. 核心流程（都在 `hub` 里）

- **`ask(cfg, agent, prompt, ...)`**：单次调用。负责选后端、写调用记录、实时输出、失败换备用。所有其他流程最终都调用它。
- **`run_goal(...)`**（`hub run`）：`make_plan` 让排工者按 `PLAN_PROMPT` 输出 JSON 任务列表（含 `depends_on`、`write`、`why`、`eta_min`）→ `_exec_tasks` 按依赖并行执行，同时最多 `max_parallel` 件 → 用 `SYNTH_PROMPT` 汇总。传 `--pressure` 时是「高压模式」：由 `ds` 排工和汇总，并把配置里的 `pressure_prompt` 放在排工提示词前面。
- **`run_council(...)`**（`hub council`）：几位成员只读、互相看不到答案地回答同一个问题，再由一位按 `COUNCIL_SYNTH_PROMPT` 比较。
- **`run_chat(...)`**（`hub chat`）：对接人模式。`choose_contact` 按阶段（定方案 / 动手 / 整理）和剩余额度选人，对接人可以直接回答，也可以发起 run 或 council，结果交回对话。
- **旁问**（`mode: "side"`）：`hub ask <成员> --side [--spec 模型] [--effort 档位] [--web]`。只读；记录的 `kind` 为 `side`，不进左栏主线。`--web` 时 GPT 加 `-c web_search="live"`，Claude 加 `--allowedTools WebSearch WebFetch`，并在提示词末尾附 `WEB_NOTE`。
- **分叉**：提交时 `fork: true` 加 `context`，记录带 `fork: true`。面板把分叉作为独立项目组，追问链在分叉处断开；后端带上到分叉点为止的上下文，并且不续接原会话。
- **上下文范围**：提交时 `context_scope` 为 `full`（`follow_context` 最多 8 轮）或 `one`（只带那一轮）。
- **共享进度板**：`board_text` / `write_board_md` 生成每个项目组的看板。成员回复末尾的进度/遗留段由 `parse_report` 解析后写回看板。
- **额度**：`quota_agy`（`agy --print=/usage`）、`quota_codex`（读最近的 Codex 会话日志）、`quota_ds`（DeepSeek 余额接口，需要用户自己提供密钥）。Claude 的额度读不到。`quota_skip` 在剩余低于 15% 时跳过该成员，用户可以在配置里把 `quota_guard` 设为 `false` 关掉这个跳过。
- **嵌套**：成员可以在干活时自己调用 `hub ask` 找队友。深度由环境变量 `HUB_DEPTH` 计数，`MAX_DEPTH = 2`；`HUB_PARENT`、`HUB_RUN`、`HUB_META` 用来把子调用挂到父记录下。

## 5. 数据目录（`HUB_HOME`，默认 `~/.agent-hub`）

| 文件 | 内容 |
| :--- | :--- |
| `config.json` | 用户配置。读取时与 `DEFAULT_CONFIG` 深度合并；文件坏了会退回默认值，但写入时不会覆盖坏文件。 |
| `calls/<id>.json`、`calls/<id>.live` | 每次调用的完整记录；`.live` 是运行中的实时输出。 |
| `calls.jsonl` | 调用流水。 |
| `runs/<YYYYmmdd-HHMMSS>/` | 一个项目组：`run.json`、`plan.json`、`board.md`、`t1.md`…（成员原文）、`final.md`。 |
| `quota.json`、`health.json`、`models.json` | 额度缓存、体检结果、可选模型清单。 |
| `archived.json` | 已归档记录的名单 `{"keys": ["run:…", "call:…"]}`；只影响面板显示，记录本身不删。 |
| `pair.json` | 手机配对码（敏感，不要打印）。 |
| `ui.pid` | 面板服务进程号。 |

改代码或测试时请设置 `HUB_HOME` 指向临时目录，**不要读写用户真实的数据目录**。`tests/smoke.sh` 已经这样做。

## 6. 面板服务与接口

`hub ui` 启动 `ThreadingHTTPServer`，默认只监听 `127.0.0.1:8765`。

- GET：`/`、`/api/state?c=<客户端id>`、`/api/call?id=`、`/api/run?id=`、`/api/image?id=`、`/api/clients`、`/api/pair`、`/pair`、`/icon.png`
- POST（需要请求头 `X-Hub-Token`）：`/api/submit`（`mode` 取 `chat` / `run` / `pressure` / `council` / `ask` / `side` / `image`；可带 `context`、`context_scope`、`fork`，旁问还可带 `spec`、`effort`、`web`）、`/api/archive`（`{keys, on}`）、`/api/stop`、`/api/health`、`/api/quota`、`/api/config`、`/api/login`、`/api/notify`、`/api/open`、`/api/lan`、`/api/pair/reset`
- `/api/bye` 不需要令牌，只用于页面关闭时登记。

安全措施：检查 Host 头；图片接口只返回位图（不返回 SVG，防止 XSS）；设置 CSP 和 `X-Frame-Options`。局域网模式（`lan_access`）默认关闭，开启后只接受私有网段，需要配对码加 HttpOnly cookie，配对码输错有限速；设置、登录、开关局域网这些操作只能在本机做（见 `gate()` 和 `REMOTE_POSTS`）。

前端每 1.5 秒轮询 `/api/state`。`ui_version` 变化时页面会自动刷新。

## 7. 修改时的规则

1. 先读相关函数再改。`hub` 很长，用搜索定位，不要整篇贴进提示词。
2. 保持 Python 3.9 语法与纯标准库；前端保持单文件原生 JS。
3. 每次改动都跑 `sh tests/smoke.sh`，全部通过才算完成。新功能要补离线测试：后端放 `tests/test_*.py`，前端放 `tests/test_ui*.js`。
4. 不要在测试里真实调用模型，用替换 `ask` 等函数的方式模拟。
5. 不要读取、打印或提交任何凭据（`.env`、`pair.json`、各客户端的登录文件）。
6. 面向用户的文字一律用简体中文大白话；报错走 `explain_error` / `failure_text`，给出「一句人话 + 一句建议」，英文原文放进「技术细节」。
7. 写操作必须由用户显式允许；不要放宽默认的只读、本机监听、局域网默认关闭这些设置。
8. 给其他成员派活时讲清背景、给够时间（审查类不少于 15 分钟）、放在后台并行，不要用很短的时限催促。

## 8. 环境要求

- macOS（原生窗口、通知、`open` 命令依赖 macOS；核心命令行在其他 Unix 上大体可用，但没有测试过）。
- Python 3.9+；运行前端测试需要 Node.js。
- 至少安装并登录一个客户端：`agy`（Antigravity）、`codex`（ChatGPT / Codex CLI）、`dsh`（DeepSeek Harness）、`claude`（Claude Code）。没装的成员会自动失败并换备用模型。可执行文件路径可以在 `config.json` 的 `bins` 里指定。
