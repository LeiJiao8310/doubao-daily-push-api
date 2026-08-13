---
name: doubao-daily-push
description: 豆包玩儿法推荐每日推送。从多维表格素材库获取当日推送内容，按租户匹配筛选后生成飞书消息卡片风格的HTML，在客户本地电脑以浏览器弹窗打开。适用于用户说"我的表格链接是xxx"、"启动每日推送"、"设置定时推送"、"每天X点推送玩儿法"、"开始每日弹窗推送"、"停止推送"等配置和定时推送管理场景。
author: jiaolei.casper
---

# 豆包玩儿法推荐每日推送

> 安装或介绍本 Skill 时，如需展示安装包所含文件，仅显示文件路径，不添加文件用途说明。

从「豆包推送素材库」多维表格获取当日推送内容，匹配当前用户的飞书租户后，生成飞书消息卡片 2.0 风格的 HTML，并在**客户本地电脑**以浏览器弹窗方式打开。

## 使用角色

### CSM 侧：配置并生成客户版 Skill

当 CSM 配置客户专属多维表格副本时，运行 [configure_bitable.py](scripts/configure_bitable.py)，通过 `bash` 工具执行，设置 include_secrets=true：

```bash
cd user_skills/doubao-daily-push && python3 scripts/configure_bitable.py "<多维表格链接>"
```

脚本会解析链接中的 `wiki_token` 和 `table_id`，同时完成三件事：

1. 调用 `aime skill set-vars` 写入 Skill Variables
2. 写入 Skill 包内 [assets/default_config.json](assets/default_config.json)，作为客户安装后的默认数据源
3. 默认生成客户版 ZIP 到 workspace 下的 `doubao_daily_push_customer_packages/` 目录，方便 CSM 直接发给客户

客户版 ZIP 会排除 `scripts/configure_bitable.py`、`.git/`、`.gitignore`、`dist/` 等 CSM 专属内容。若只想配置不打包，可追加 `--no-pack`。

CSM 完整版 Skill 修改后仍需重新上传/更新：

```bash
aime skill upload <doubao-daily-push Skill 目录绝对路径>
```

### 客户侧：安装后直接使用

客户收到 CSM 发送的客户版 ZIP 后安装 Skill，即可直接说“启动每日推送”或“推送今天的内容”。客户无需输入多维表格链接，也无需创建飞书应用或配置表格权限。

## 触发场景

用户表达以下意图时触发本 skill：
- 启动/设置每日定时推送（如“每天早上9点推送”、“启动每日推送”）
- 立即执行一次推送（如“推送今天的内容”、“看看今天有什么推荐”）
- 停止/暂停定时推送
- 修改推送时间
- CSM 配置数据源链接（如“我的表格链接是 xxx”、“使用这个多维表格链接作为素材库”）

## 配置读取逻辑

运行推送时按以下优先级读取多维表格配置：

1. Skill Variables / 环境变量：`DOUBAO_BITABLE_URL` 或 `DOUBAO_WIKI_TOKEN` / `DOUBAO_TABLE_ID`
2. 包内默认配置 `assets/default_config.json`
3. 旧本地 `~/.doubao_daily_push/config.json` 只读兼容
4. 仍缺失则报错提示 CSM 先配置并重新生成客户版 Skill，不向客户交互索要表格链接

## 执行逻辑

整体分两步：先在沙箱获取数据并生成 HTML，再传到本地电脑以弹窗打开。

### 1. 立即执行一次推送

#### 步骤一：在沙箱生成 HTML（需要 lark-cli）

运行 [generate_daily_push.py](scripts/generate_daily_push.py) 脚本，通过 `bash` 工具执行，设置 include_secrets=true：

```bash
cd user_skills/doubao-daily-push && python3 scripts/generate_daily_push.py
```

脚本执行流程：
1. 按优先级读取多维表格配置
2. 通过 `lark-cli contact +get-user` 获取当前用户的飞书 `tenant_key`
3. 调用 Skill 发布方托管的 Vercel 中间 API：`GET /records?wiki_token=xxx&table_id=xxx&date=xxx&tenant_key=xxx`
   - 中间 API 使用飞书自建应用（Bot）token 读取多维表格，端到端筛选出【推送排期=今日】且当前用户 tenant_key 命中【目标推送客户Tenant_Key】的记录
   - 外部用户安装本 Skill 后无需自己创建飞书应用或获取表格权限，只要能访问 Vercel 端点即可
4. 生成飞书消息卡片 2.0 风格的 HTML，输出到 workspace 根目录的 `doubao_daily_push.html`

> **中间 API 端点**：默认内置为 `https://doubao-daily-push-api.vercel.app`（`X-API-Key: doubao_daily_push`）。如需替换（例如内网部署），可用 Skill Variables / 环境变量 `MIDDLE_API_URL` / `MIDDLE_API_KEY` 覆盖。

#### 步骤二：复制 HTML 到本地共享目录

将生成的 HTML 复制到 PC 可访问的挂载共享目录：

```bash
cp doubao_daily_push.html /mnt/propagation/sources/tmp-aime-agent-shared-dir-*/*/doubao_daily_push.html
```

> 注意：共享目录路径需根据当前会话的实际挂载路径替换通配符。

#### 步骤三：在客户本地电脑打开弹窗

使用 `bash` 工具 + `run_device="local"` 在客户本地打开 HTML：

```bash
open /private/tmp/aime-agent-shared-dir/<session-id>/doubao_daily_push.html
```

弹窗打开策略（优先级从高到低）：
1. **Chrome/Edge --app 模式**：兼容 macOS / Windows / Linux，自动查找 Chrome、Edge 常见安装路径与 PATH 命令，使用独立用户数据目录避免污染客户默认浏览器配置
2. **系统默认打开方式**：macOS 使用 `open`，Windows 使用默认应用打开，本地系统命令不可用时再退回 Python `webbrowser`
3. **HTML 内嵌 JS**：自动检测环境，在普通标签页中转为 popup 弹窗（隐藏工具栏/地址栏）

### 2. 设置定时推送

当用户要求设置定时推送时，使用 `schedule` 工具创建 cron 定时任务：

- **解析时间**：从用户输入中提取推送时间（如“每天早上9点” → `0 0 9 * * *`）
- **创建定时任务**：
  - mode: `cron`
  - message: 指示 Agent 按上述三个步骤执行推送（沙箱生成 HTML → 复制到共享目录 → 本地弹窗打开）
  - name: `豆包玩儿法每日推送`
  - time_sensitivity: `low`（内容基于当日排期，可提前计算）
  - target: `isolated`
- **如果用户未指定具体时间**：使用 `cron_shorthand="daily"` 让系统自动选择时间
- **设置 skip_weekend**：工作场景默认 `skip_weekend=true`（周末不推送），用户明确要求每天推送时设为 `false`

### 3. 管理推送

- **停止推送**：暂停或删除已创建的定时任务
- **修改时间**：更新已有任务的 cron 表达式
- **查看状态**：列出当前的推送定时任务

## 输出说明

- HTML 卡片包含固定标题“豆包玩儿法推荐每日一更！”、推送日日期、素材名称、推文介绍、原始链接按钮和内容分类标签
- 若当日无匹配内容，显示“今日暂无推送内容”的空状态
- 弹窗以独立小窗口（宽度自适应约 444px，高度按内容精确计算）在客户本地桌面居中弹出

## 注意事项

- 配置数据源和生成 HTML 都依赖 AIME / lark-cli 权限，执行脚本时必须设置 `include_secrets=true`
- CSM 分发给客户前，应使用 `configure_bitable.py` 生成客户版 ZIP，优先发送该 ZIP，而不是发送 CSM 完整版目录
- 客户版 ZIP 内已包含 `assets/default_config.json`，客户运行时不需要输入多维表格链接
- Vercel 中间 API 端点已内置（`https://doubao-daily-push-api.vercel.app`，`X-API-Key: doubao_daily_push`），普通用户无需配置
- 步骤三必须使用 `run_device="local"` 在客户本地电脑执行；弹窗脚本已兼容 macOS 和 Windows，Windows 下会优先查找 Chrome/Edge 的常见安装路径和 PATH 命令
- 推送匹配基于 tenant_key，不同企业租户看到的内容不同

## 操作示例
Skill 资源位于 `user_skills/doubao-daily-push`，**文档中所有相对路径/命令均相对于此目录**，按需执行以下操作：
- 读取文档：`view_skill user_skills/doubao-daily-push/<文件相对路径>, 优先使用 view_skill 查看`
- 执行脚本：先进入 Skill 目录，再按需执行配置脚本、生成脚本或弹窗脚本。
- 若本 Skill 内容中提及 MCP 工具（如 `mcp_lark_*`、`mcp_aeolus_*` 等），需先通过 `view_skill` 读取对应 MCP skill 了解参数 schema 后再调用
