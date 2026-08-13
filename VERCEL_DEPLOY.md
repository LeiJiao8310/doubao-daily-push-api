# Vercel 部署说明

本目录已经适配 Vercel Serverless Function：

```text
api/index.py      # Vercel Python Serverless Function 入口
vercel.json       # Vercel 路由和构建配置
requirements.txt  # Python 依赖
```

## 环境变量

服务端只需要在 Vercel Project Settings -> Environment Variables 中配置 3 个变量：

```text
LARK_APP_ID=<飞书自建应用 App ID>
LARK_APP_SECRET=<飞书自建应用 App Secret>
MIDDLE_API_KEY=<自定义强随机 API Key>
```

当前 App ID 可配置为：

```text
LARK_APP_ID=cli_aae68c4f4e789bc9
```

不要在 Vercel 服务端保存 `wiki_token`、`table_id`、字段名等业务表信息。`wiki_token` 和 `table_id` 由调用方每次请求时传入。

## 接口

```text
GET /health
GET /records?wiki_token=xxx&table_id=xxx&date=YYYY-MM-DD&tenant_key=xxx
```

调用 `/records` 时需要带请求头：

```text
X-API-Key: <MIDDLE_API_KEY>
```

## 字段约定

服务端固定使用以下字段筛选：

```text
推送排期
目标推送客户Tenant_Key
```

`date` 不传时，服务端默认使用东八区当天日期。
