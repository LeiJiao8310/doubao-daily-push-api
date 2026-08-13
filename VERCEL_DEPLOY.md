# Vercel 部署说明

本目录已经适配 Vercel Serverless Function：

```text
api/index.py      # Vercel Python Serverless Function 入口
vercel.json       # Vercel 路由和构建配置
requirements.txt  # Python 依赖
```

## 环境变量

在 Vercel Project Settings -> Environment Variables 中配置：

```text
LARK_APP_ID=cli_aae68c4f4e789bc9
LARK_APP_SECRET=<你的飞书 App Secret>
MIDDLE_API_KEY=<自定义强随机 API Key>
LARK_WIKI_TOKEN=XzprwzxmuiwHBUkYMcIcPZXBn0g
LARK_TABLE_ID=tblcyon9vA9y1BLx
DATE_FIELD=date
TENANT_KEY_FIELD=tenant_key
DEFAULT_PAGE_SIZE=100
```

如果多维表字段名不是 `date` 和 `tenant_key`，请把 `DATE_FIELD`、`TENANT_KEY_FIELD` 改成真实字段名。

## 接口

```text
GET /health
GET /records?date=YYYY-MM-DD&tenant_key=xxx
```

调用 `/records` 时需要带请求头：

```text
X-API-Key: <MIDDLE_API_KEY>
```
