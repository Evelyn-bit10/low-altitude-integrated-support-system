# DeepSeek 调度辅助接口

`POST /api/ai/advice` 接收文本和可选的 `program_type`（`arrival` 或 `departure`，默认为 `arrival`）。服务端复制当前环境，使用独立的只读候选计算与现有风险、评分引擎生成上下文，然后将上下文和问题发送给 DeepSeek。发送前请确认有权向外部服务提供这些数据及用户输入；上下文包含机场、气象、候选和风险信息。

响应中的 `captured_at` 是快照采集时间，不是观测时间。当前数据源没有提供经核验的观测时间和来源，默认返回 `INSUFFICIENT_DATA`，不调用模型，也不提供推荐方向。服务端设置 `ADVISORY_SHOW_DEMO=1` 可展示内置模拟候选，始终标记仅供演示，不能用于运行，也不会发给模型。客户端参数不能启用此模式。

为未来服务端数据适配器预留的元数据为快照对象 `advisory_sources`：`meteo`、`obstacles`、`airspace` 各包含 `source`、带时区的 `observed_at` 和由可信服务端适配器设置的 `trusted: true`。必须显式设置 `ADVISORY_MAX_AGE_SECONDS` 为正数，且三项均通过检查，才可进入后续流程。该阈值只是配置参数，不代表运行标准；当前没有生产适配器，不能把上述字段视为已接入现场数据。快照和其元数据须由同一服务端适配器一起提供。

每次成功构造评估上下文时，服务端生成唯一的 `assessment_id`。建议响应通过 `context.assessment_id` 返回，结论接口直接返回该字段；建议请求的相应审计记录也包含它。每次请求都会重新采集和计算，两个接口的标识通常不同。标识仅用于关联一次评估，不是数据源版本或内容哈希；系统不保存完整评估快照，不能据此回放，也不能替代带身份的人工复核记录。预先拒绝或上下文构建失败的请求没有评估标识。

模型输出可能有误，不应视为控制或放行指令。接口不发布程序、不控制无人机，`validated` 和 `executed` 固定为 `false`，必须由授权人员核实数据并独立完成业务及安全检查。候选计算失败时接口返回 503，不请求 DeepSeek。该接口不实现多机排队；原有后台自动调度及其发布行为不受本改造约束。

## 结论码契约

`context.engine_verdict` 是确定性引擎结论，模型只能解释、不得改写；`/api/ai/advice` 与 `/api/ai/verdict` 返回同一结构：

| 结论码 | 含义 | 是否调用模型 |
| --- | --- | --- |
| `AVAILABLE_CANDIDATES` | 存在可评估候选，返回推荐方向 | 是 |
| `NO_AVAILABLE_CANDIDATE` | 8 个方向全部不可用 | 否，返回 `refusal` |
| `INSUFFICIENT_DATA` | 数据来源或时效不明、无当前程序或命中限制 | 否，返回 `refusal` |

红线（`hard_forbid`）在确定性引擎里计算，模型不得反向表述：环境风险为禁飞级（`FORBID`）、风速超过机型侧风限制、能见度低于 500 m。

## 拒绝 / 降级语义

- `POST /api/ai/advice` 命中 `NO_AVAILABLE_CANDIDATE` 或 `INSUFFICIENT_DATA` 时**不调用 DeepSeek**，直接返回 200，`advice` 为 `null`，`refusal.code` / `refusal.reason` 说明原因。
- 模型上游失败（429 / 401 / 网络错误 / 超时 / 非法或截断响应）时不再抛 5xx，返回 200，`advice` 为 `null`，`fallback.reason` 与 `fallback.message` 说明已回落引擎结论。
- 缺密钥或配置非法时，可信数据条件下返回 200 和 `fallback.reason=model_config_unavailable`；消息空白或超长仍返回 422。

## 提示注入与安全表述

- 消息命中指令覆盖黑名单（如「忽略之前 / 忽略上述 / 系统提示词 / 直接放行 / ignore previous instructions / jailbreak」等）时返回 400，且不发送给模型。
- 模型输出命中关键词时，正文被隐藏并提示需要复核。关键词可能误报、漏报，不能证明内容安全，也不构成语义分歧检测。

## 只读确定性接口

```
GET /api/ai/verdict?program_type=arrival
```

不调用模型、不需要密钥，返回 `engine_verdict`、`candidates`、`limitations`。适合决策页在实时模式下先加载引擎结论，再决定是否请求模型。

## 审计

进入处理的 AI 建议请求，以及 AI 建议和审计查询的鉴权拒绝事件，会尝试写入 `backend/logs/ai_audit.jsonl`（路径可用 `ADVISORY_AUDIT_FILE` 覆盖，已由 `.gitignore` 忽略）。AI 建议请求的参数校验失败时仍返回 422，并尝试记录 `validation_rejected` 事件，不保存输入、输入摘要或校验详情。鉴权检查异常尝试记录固定原因 `auth_check_failed`。这些拒绝事件的日志写入失败不改变接口结果。建议请求只记 `message_sha256` 与 `message_length`，**不记问题原文与模型回复原文**；鉴权拒绝事件记录接口、状态码、角色及固定原因，不记录令牌或请求正文。关闭鉴权时角色记为匿名。建议请求字段为 `ts / request_id / actor_role / program_type / message_sha256 / message_length / injection_detected / freshness / conclusion / model / safety_claim_detected / refused / upstream_error / duration_ms`。只读查询：

上下文计算失败时，接口返回 503，审计记录 `upstream_error=context_unavailable`，不记录异常原文。审计查询默认关闭；启动服务前需设置 `AUTH_ENABLED=true`，通过 `DEMO_TOKENS` 配置独立管理员令牌，并在请求中使用 `X-Token`。内置演示令牌不能读取审计。无效的非空 `DEMO_TOKENS` 配置不会回退到内置令牌。

```
GET /api/ai/audit?limit=50
X-Token: <configured-admin-token>
```

查询按行读取并只保留最近 1 至 200 行，再按新到旧返回其中可解析的记录；损坏的 JSON 行会被跳过，因此返回条数可能少于请求值。查询仍需扫描整个文件，单行长度也没有限制；文件编码损坏或读取失败时返回 503。角色字段不能替代可追溯的个人身份。

### 模型调用审计要求

`ADVISORY_REQUIRE_AUDIT` 默认值为 `0`，模型路径上的审计写入失败只记录警告。设为 `1` 后，在允许进入模型处理的请求中，服务端先写入并同步 `advisory_started` 事件。写入或文件同步失败时返回 503，不发出模型请求。其他配置值也会在这条路径返回 503。客户端不能覆盖此设置。

处理结束后，服务端使用相同的 `request_id` 和 `assessment_id` 写入并同步结果记录，成功后才返回建议或降级结果。如果结束记录写入失败，服务端返回 503，此时模型可能已经收到请求。开始事件只表示服务端进入处理，无法据此确认外部模型收到了请求。输入校验、鉴权拒绝和数据不足等提前返回路径仍会尝试记录审计。文件同步无法保证保留期限和完整追溯。

## 评估回放与人工复核

`POST /api/ai/advice` 归档确定性评估上下文（包括数据不足的结果），不保存问题原文或模型回答。`ADVISORY_SNAPSHOT_FILE` 与 `ADVISORY_REVIEW_FILE` 可覆盖默认的 `logs/ai_assessments.jsonl` 和 `logs/ai_reviews.jsonl`；严格审计模式下，快照写入或同步失败返回 503。

开启鉴权后，复核需要同时在 `DEMO_TOKENS` 绑定管理员角色、在 `DEMO_IDENTITIES` 绑定稳定个人标识（格式为 `令牌:个人标识`，多项用逗号分隔）。内置演示令牌不能复核。`GET /api/ai/assessments/{assessment_id}` 回放已归档的评估上下文；`POST /api/ai/reviews` 接收 `assessment_id` 和 `decision`（`acknowledged`、`disagreed` 或 `needs_more_info`），服务端绑定审阅人、UTC 时间和快照哈希；`GET /api/ai/reviews` 查看近期记录。复核不改变引擎结论，也不会触发放行或执行。

当前仅回放已保存的上下文，不能重新计算历史评估。静态令牌和本地 JSONL 仅用于开发验证，不提供生产身份校验、防篡改、保留期限管理或多进程写入保障。

## 配置与启动

在 `backend/.env.deepseek` 的 `api_key` 中填写密钥，文件内容为 JSON：

```json
{
  "api_key": "你的 API 密钥",
  "model": "deepseek-flash"
}
```

本地配置已被 Git 忽略，不要将密钥写入示例文件或提交到仓库。`DEEPSEEK_API_KEY` 和 `DEEPSEEK_MODEL` 环境变量存在时优先于文件中的值。每次请求时重新读取本地文件。然后启动后端：

```powershell
cd flight\flycontrol\low-altitude-demo\backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

另一个 PowerShell 窗口中请求：

```powershell
$body = @{ message = "请列出安排无人机巡检任务前需要确认的信息" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/ai/advice -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

如启用 `AUTH_ENABLED=1`，按照现有权限规则传入 operator 或 admin 的 `X-Token`。项目默认关闭鉴权，且默认演示令牌不适用于生产环境；不要将该接口直接暴露到不可信网络。调用会产生外部 API 请求和费用，具体依赖账户及服务情况。
