# doubao-daily-push 中间 API（Vercel）

这是用于 `doubao-daily-push` Skill 的轻量中间 API。服务端只托管飞书 App Secret，并通过调用方传入的 `wiki_token` 和 `table_id` 读取指定多维表格数据。

## 目录结构

```text
api/index.py      # Vercel Python Serverless Function 入口
vercel.json       # Vercel 路由和构建配置
requirements.txt  # Python 依赖
```

## 环境变量

服务端只需要配置 3 个环境变量：

```bash
LARK_APP_ID=cli_aae68c4f4e789bc9
LARK_APP_SECRET=<飞书 App Secret，不要写入代码仓库>
MIDDLE_API_KEY=<自定义访问密钥，只给 Skill 使用>
```

`wiki_token` 和 `table_id` 不在服务端保存，由 Skill 每次请求时传入。

## 接口

### 健康检查

```bash
GET /health
```

### 获取当日推送数据

```bash
GET /records?wiki_token=xxx&table_id=xxx&tenant_key=xxx&date=2026-08-13
X-API-Key: <MIDDLE_API_KEY>
```

`date` 不传时，默认按东八区取当天日期。

服务端固定按以下字段筛选：

```text
推送排期
目标推送客户Tenant_Key
```

返回示例：

```json
{
  "date": "2026-08-13",
  "tenant_key": "xxx",
  "wiki_token": "xxx",
  "table_id": "xxx",
  "count": 1,
  "records": [
    {
      "record_id": "recxxxx",
      "fields": {}
    }
  ]
}
```

## 本地验证

```bash
pip install -r requirements.txt
export LARK_APP_ID='cli_aae68c4f4e789bc9'
export LARK_APP_SECRET='你的 App Secret'
export MIDDLE_API_KEY='一个自定义 API Key'
python api/index.py
```

Vercel 环境下不需要本地启动命令，推送到 GitHub 后由 Vercel 自动部署。

## App Secret 存放建议

不要把 `LARK_APP_SECRET` 写入代码、README、Skill 源码或 Git 仓库。生产环境只放在 Vercel Environment Variables 中。Skill 侧只保存 `MIDDLE_API_KEY`，以及用户配置的数据源 `wiki_token` 和 `table_id`。
