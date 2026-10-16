# mathmodel

> 英文文档见 [README.md](README.md)

面向 [ZCode](https://zcode.z.ai/) 的自主数学建模 agent，为竞赛写作（国赛 / 美赛 / 研数模）而做。它读题、确定决策变量、**把模型数值求解出来**、验证、画图、成文。

它不请求许可、不评判动机。这不是姿态，而是架构：动作就是在持久内核里执行的 python，意图与效果之间根本不存在可以塞进一句"你确定吗？"的中间层。这里没有任何东西审查你的目的、没有东西插入免责声明；**在循环内部**，操作者的指令是唯一权威。

**但这不等于"无限制"，两者的区别写在这里而不是含糊带过。** 见[下面](#这个-agent-不能声称能绕过的限制)——有三类限制是任何配置都关不掉的，其中一类（模型自身训练）根本无法从插件层面解除。

```
/solve 某零件厂用 A、B 两种原料生产甲、乙两种产品……
  -> 42 t / 16 t，190 千元，影子价格 u1=1（但只对前 5 吨成立）
  -> 图 + 表 + 灵敏度 + 报告，每个数字都来自实际执行的 cell
```

---

## 安装

### 方案 A：本地目录（最快）

在 `~/.zcode/cli/config.json` 里指向插件目录：

```json
{
  "plugins": {
    "dirs": ["/path/to/mathmodel"]
  }
}
```

就这些。`dirs` 来源的插件**默认即启用**；它的 id 是 `mathmodel@inline`（ZCode 把目录加载的插件标在 `inline` marketplace 下），所以你只在想**关掉**它时才需要写 `enabledPlugins`：

```json
{ "plugins": { "enabledPlugins": { "mathmodel@inline": false } } }
```

### 方案 B：从 GitHub 装（真正的 marketplace）

本仓库带 `.claude-plugin/marketplace.json`，可作为 marketplace 注册。你注册时用的键名就是 `@` 后缀，因此这里插件 id 是 `mathmodel@mathmodel`：

```json
{
  "plugins": {
    "extraKnownMarketplaces": {
      "mathmodel": { "source": { "source": "github", "repo": "sun-zihang/mathmodel" } }
    },
    "enabledPlugins": { "mathmodel@mathmodel": true }
  }
}
```

> 方案 B 通过普通 `git` 拉取仓库，所以仓库必须**公开**（或者你本机的 git 凭据已能通过 GitHub 认证）。私有仓库请用方案 A。

重启 ZCode。MCP server 以 `python engine/mcp_server.py` 启动，因此 `python` 必须在 `PATH` 上；建模工具还需要：

```
pip install scipy numpy matplotlib sympy pandas
pip install pulp        # 可选：经 CBC 求解整数规划
```

不装也不会崩——`solve_lp` 退回纯 python 单纯形，`plot` 退回 ASCII 图——但它会明确告知走了哪条退路，而不是悄悄给你一个质量不同的答案。

---

## 你得到什么

| 工具 | 作用 |
|---|---|
| `mcp__mathmodel__run_task` | 整个任务无人值守跑完：规划 → 求解 → 验证 → 绘图 → 成文。返回报告与转录文件路径。 |
| `mcp__mathmodel__run_python` | 持久命名空间里的 python（import 与变量跨步骤保留）。 |
| `mcp__mathmodel__read_file` / `write_file` | 文件。读取结果会被隔离包裹（见下文）。 |
| `mcp__mathmodel__shell` | Shell。 |
| `mcp__mathmodel__web_fetch` | 抓 URL，结果被隔离包裹。 |
| `mcp__mathmodel__list_models` | 列出当前路由可用的模型。 |
| `mcp__mathmodel__blast_radius` | 报告代码实际会在哪里执行。只读。 |

另有 `tools_modelling`，可在 `run_python` 里 import：`solve_lp_max`、`shadow_price_analysis`、`newton`、`bisect`、`rk4`、`describe`、`ols`、`pearson`、`sensitivity`、`plot`、`ascii_plot`、`table`。

**ZCode 自带额度**由 ZCode 驱动本循环时消耗——用的是它自己的登录，任何凭据都不会进入本进程。插件从不冒用 plan token。

---

## 这个 agent 不能声称能绕过的限制

"零审批"是一个精确的说法：**本代码与 ZCode 权限层里没有任何一道闸会对你的指令暂停、审查或否决。** 它不是在说"这个 agent 无限制"。有三类限制在任何配置下都成立；把它们含糊过去，正是本仓库那套测试存在的意义——专抓这种假完整。

**1. 模型自身的训练——插件层面无法移除。** 每条路由都在跟一个 hosted 模型对话（Zai 的、你自己的、或网关的）。如果底层模型拒绝写恶意软件、危险物质配方等，那个拒绝存在于它的权重里。任何 harness 配置都够不着它。这是全系统最深的一道边界，也最容易被"已越狱 agent"这类宣传曲解——本项目不做此类宣称。

**2. 本代码里的机械闸，防的是失控循环，不是防你。** `max_steps`（默认 60）、单步超时、60000 字符输出上限、抓取超时、容器 `--memory/--cpus`。它们存在，只是因为一个产生幻觉的循环会乐意向烧光你的上下文窗口、硬盘或 API 额度跑下去；它们都是 `config.json` 里的数字，全部可调。它们从不追问你*为什么*要做某件事。

**3. 你自己配置的宿主设置。** ZCode 的决策顺序把 `requiresUserInteraction` 与 `alwaysAsk` 排在 yolo 旁路**之前**，并尊重 `disallowedTools` / 项目级 deny 规则。本插件一个都没声明，也不自带任何项目规则集——所以默认配置下这些闸一道都不会触发。若你日后自己加上，以你的为准。这是宿主的性质，不是插件可以承诺掉的东西。

以下是刻意保留的边界（是设计，不是遗漏）：

**1. 提示注入隔离。** 任何来自网页或文件的内容都会被包进 `QUARANTINED` 块，并被声明为数据、而非指令。这不是防你自己——是防*别人*的网页怂恿你的 agent 去 `rm -rf ~/.ssh`。你自己的指令永远不会被隔离；测试套件把这两半都钉住了。

**2. 不碰第三方账号体系。** 插件把本地网关当模型服务消费。它不驱动该网关的多账号轮换、自动签到，也不动它背后厂商的登录。前者是模型调用；后者是花别人的额度池、撞别人的风控，会损害第三方并让你的账号被处置。这条线只说一次：它关于别人的系统，不关于限制你在自己机器上做什么。

---

## 测试

六项，全部可运行，没有一项是装饰：

```
python tests/test_tools.py       # 35 条断言：求解器、统计、数值、退化输入
python tests/test_manifest.py    # 插件接线：每个 userConfig 项都被读取、每条路径都存在
python tests/test_smoke.py       # 完全按 ZCode 的方式驱动 MCP server，含干净退出
python tests/test_promises.py    # 本 README 的承诺：容器拒绝、隔离、步数上限
python tests/check_no_scipy.py   # 在无 scipy 的解释器上验证单纯形 + ASCII 图退路
python tests/check_secrets.py --selftest && python tests/check_secrets.py --gate
                                 # 发布门禁；--selftest 先证明这些正则真的能开火
```

最后这项存在的理由：一个只会打印"0 matches"的扫描器，和真正干净的仓库根本无法区分——这里曾有一个空正则的 bug 就是这样，报了一个漂亮的 0，实际什么都没扫到。

`test_tools` 里最重要的那条对报告至关重要：**纯 python 单纯形与 scipy 必须在最优解*和*影子价格上都一致。** 它们曾因符号差一次，那种错在演示里看不见，在提交稿里致命。

## 为什么工具带有立场

`shadow_price_analysis` 之所以存在，是因为灵敏度分析里最典型的错误就是把影子价格乘以拟议的增量。影子价格是*局部*的——只在基不变时成立——而赛题恰恰会选在那个乘积会算错的地方。以上例而言：u₁ = 1 千元/吨，而 +10 吨只值 **5**，不是 10，因为第三条约束在 +5 处开始咬住。该函数重新求解，报告真实增益，并打印有效区间。

报告里不允许出现任何未经计算的数字。每次运行都会在 `MATHMODEL_DATA_DIR/sessions/` 下写一份 JSONL 转录，所以"190 从哪来的"三周后仍可回答。

## 许可

MIT
