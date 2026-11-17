# DeepSeek 调度辅助接口

`POST /api/ai/advice` 接收文本和可选的 `program_type`（`arrival` 或 `departure`，默认为 `arrival`）。服务端复制当前环境，使用独立的只读候选计算与现有风险、评分引擎生成上下文，然后将上下文和问题发送给 DeepSeek。发送前请确认有权向外部服务提供这些数据及用户输入；上下文包含机场、气象、候选和风险信息。

响应中的 `context` 包含采集时间、数据限制、候选方向和演示风险评估。采集时间不是观测时间：当前来源未提供可靠观测时间，新鲜度始终标记为 `unknown`，也无法判断是否过期。当前程序不存在时风险为 `null`；没有可用候选时会明确提示。数据源可能为演示数据，快照采集不是跨数据源的原子操作，检查通过不代表实际安全或民航审批。

模型输出可能有误，不应视为控制或放行指令。接口不发布程序、不控制无人机，`validated` 和 `executed` 固定为 `false`，必须由授权人员核实数据并独立完成业务及安全检查。候选计算失败时接口返回 503，不请求 DeepSeek。该接口不实现多机排队；原有后台自动调度及其发布行为不受本改造约束。

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
