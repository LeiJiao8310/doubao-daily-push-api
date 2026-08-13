# FaaS 创建参数模板 + doubao-daily-push 中间 API

## 一、FaaS 创建参数模板

推荐入口：

- DevOps 一键创建 FaaS：https://cloud.bytedance.net/appfactory_v2/createproject/be?mode=FaaS
- ByteFaaS 控制台：https://cloud.bytedance.net/faas/func_list

建议参数：

| 参数 | 建议填写 |
|---|---|
| 函数名 | `doubao-daily-push-api` |
| 函数 PSM | 按团队规范填写一个唯一 PSM，例如 `your_team.doubao.daily_push_api` |
| 部署环境 | 先 `boe`，验证后再 `production` |
| 部署地区 | 优先选择 CN / 华北 |
| 服务树 / 服务组 | 选择你所在团队有权限的服务树 |
| Protocol | `HTTP` |
| Runtime | Python 3.8+ 或 Native Python，按平台模板可选项选择 |
| 创建方式 | 长期维护建议 SCM 仓库；快速验证可在线编辑 |
| 实例规格 | 默认即可 |
| 请求超时 | 10s～30s |
| 初始化超时 | 30s～60s |
| 触发器 | 默认 HTTP；如需自定义域名/TLB，再新增 Consul 触发器 |
| 审核机制 | BOE 验证可先不开；生产按团队规范开启 |

## 二、环境变量

必须配置：

```bash
LARK_APP_ID=cli_aae68c4f4e789bc9
LARK_APP_SECRET=<从 KMS / 敏感配置读取，不要写进代码仓库>
MIDDLE_API_KEY=<自定义访问密钥，只给 Skill 使用>
LARK_WIKI_TOKEN=XzprwzxmuiwHBUkYMcIcPZXBn0g
LARK_TABLE_ID=tblcyon9vA9y1BLx
```

可选配置：

```bash
DATE_FIELD=date
TENANT_KEY_FIELD=tenant_key
DEFAULT_PAGE_SIZE=100
PORT=8000
```

如果多维表字段名不是 `date` 和 `tenant_key`，请把 `DATE_FIELD`、`TENANT_KEY_FIELD` 改成真实字段名。

## 三、接口说明

### 健康检查

```bash
GET /health
```

### 获取当日推送数据

```bash
GET /records?tenant_key=xxx&date=2026-08-13
X-API-Key: <MIDDLE_API_KEY>
```

`date` 不传时，默认按中国时区取当天日期。

返回示例：

```json
{
  "date": "2026-08-13",
  "tenant_key": "xxx",
  "count": 1,
  "records": [
    {
      "record_id": "recxxxx",
      "fields": {}
    }
  ]
}
```

## 四、本地验证

```bash
pip install -r requirements.txt
export LARK_APP_SECRET='你的 App Secret'
export MIDDLE_API_KEY='一个自定义 API Key'
python app.py
```

然后请求：

```bash
curl 'http://127.0.0.1:8000/records?date=2026-08-13&tenant_key=xxx' \
  -H 'X-API-Key: 一个自定义 API Key'
```

## 五、App Secret 存放建议

不要把 `LARK_APP_SECRET` 写入代码、README、Skill 源码或 Git 仓库。

推荐做法是：生产环境把 App Secret 放到 KMS、Vault 或 FaaS 平台的敏感配置/环境变量中，运行时以环境变量形式注入服务。Skill 侧只保存 `MIDDLE_API_KEY`，通过中间 API 读取业务数据。

更安全的生产做法还包括：定期轮换 App Secret 和 `MIDDLE_API_KEY`，接口只允许白名单路径，日志里不要打印 App Secret、tenant_access_token、完整请求头和敏感业务字段。
