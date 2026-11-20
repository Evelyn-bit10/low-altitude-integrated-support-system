# DeepSeek 调度辅助接口

`POST /api/ai/advice` 接收文本和可选的 `program_type`（`arrival` 或 `departure`，默认为 `arrival`）。服务端复制当前环境，使用独立的只读候选计算与现有风险、评分引擎生成上下文，然后将上下文和问题发送给 DeepSeek。发送前请确认有权向外部服务提供这些数据及用户输入；上下文包含机场、气象、候选和风险信息。

响应中的 `context` 包含采集时间、数据限制、候选方向和演示风险评估。采集时间不是观测时间：当前来源未提供可靠观测时间，新鲜度始终标记为 `unknown`，也无法判断是否过期。当前程序不存在时风险为 `null`；没有可用候选时会明确提示。数据源可能为演示数据，快照采集不是跨数据源的原子操作，检查通过不代表实际安全或民航审批。

模型输出可能有误，不应视为控制或放行指令。接口不发布程序、不控制无人机，`validated` 和 `executed` 固定为 `false`，必须由授权人员核实数据并独立完成业务及安全检查。候选计算失败时接口返回 503，不请求 DeepSeek。该接口不实现多机排队；原有后台自动调度及其发布行为不受本改造约束。

## 结论码契约

`context.engine_verdict` 是确定性引擎结论，模型只能解释、不得改写；`/api/ai/advice` 与 `/api/ai/verdict` 返回同一结构：

| 结论码 | 含义 | 是否调用模型 |
| --- | --- | --- |
| `AVAILABLE_CANDIDATES` | 存在可评估候选，返回推荐方向 | 是 |
| `NO_AVAILABLE_CANDIDATE` | 8 个方向全部不可用 | 否，返回 `refusal` |
| `INSUFFICIENT_DATA` | 无当前程序，无法计算风险 | 否，返回 `refusal` |

红线（`hard_forbid`）在确定性引擎里计算，模型不得反向表述：环境风险为禁飞级（`FORBID`）、风速超过机型侧风限制、能见度低于 500 m。

## 拒绝 / 降级语义

- `POST /api/ai/advice` 命中 `NO_AVAILABLE_CANDIDATE` 或 `INSUFFICIENT_DATA` 时**不调用 DeepSeek**，直接返回 200，`advice` 为 `null`，`refusal.code` / `refusal.reason` 说明原因。
- 模型上游失败（429 / 401 / 网络错误 / 超时 / 非法或截断响应）时不再抛 5xx，返回 200，`advice` 为 `null`，`fallback.reason` 与 `fallback.message` 说明已回落引擎结论。
- 缺密钥或本地配置非法仍返回 503；消息空白或超长仍返回 422。

## 提示注入与安全表述

- 消息命中指令覆盖黑名单（如「忽略之前 / 忽略上述 / 系统提示词 / 直接放行 / ignore previous instructions / jailbreak」等）时返回 400，且不发送给模型。
- 模型输出命中「可以放行 / 已批准 / 已授权 / 确认安全 / 保证安全 / approved / authorized / cleared for」等措辞时，`safety_guard.triggered` 为 `true`，前端据此标记分歧并强制人工复核。

## 只读确定性接口

```
GET /api/ai/verdict?program_type=arrival
```

不调用模型、不需要密钥，返回 `engine_verdict`、`candidates`、`limitations`。适合决策页在实时模式下先加载引擎结论，再决定是否请求模型。

## 审计

每次调用写 `backend/logs/ai_audit.jsonl`（路径可用 `ADVISORY_AUDIT_FILE` 覆盖，已由 `.gitignore` 忽略）。只记 `message_sha256` 与 `message_length`，**不记问题原文与模型回复原文**，字段为 `ts / request_id / actor_role / program_type / message_sha256 / message_length / injection_detected / freshness / conclusion / model / safety_claim_detected / refused / upstream_error / duration_ms`。只读查询：

```
GET /api/ai/audit?limit=50
```

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
