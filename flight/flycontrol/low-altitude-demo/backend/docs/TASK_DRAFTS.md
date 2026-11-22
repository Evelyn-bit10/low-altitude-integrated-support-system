# 任务草稿检查

`POST /api/task-drafts/check` 接收人工填写的任务草稿，检查字段是否填写，返回缺失字段。该接口不需要设备或现场数据，不保存草稿，也不启动、批准或执行任务。

示例请求：

```json
{
  "task_id": "TASK-001",
  "aircraft_id": "AIRCRAFT-001",
  "operation": "departure",
  "site_id": "SITE-001",
  "payload_description": "无载荷",
  "payload_weight_kg": 0
}
```

字段均可暂时不填；`operation` 仅接受 `arrival` 或 `departure`，重量单位为千克，须为非负数。字段清单是草稿阶段的最小信息，不代表业务方已确认最终必填规则。`draft_complete` 仅表示上述字段均已填写，不代表数据真实、载荷适配、具备空域许可或允许飞行。响应始终标明 `operationally_validated: false` 和 `executed: false`。

门户入口为「业务管理 → 任务草稿检查」。草稿仅在当前页面使用，刷新或离开页面会清空。任务保存、载荷适配计算和 AI 咨询接入尚未提供。启用鉴权时，可在「AI 决策 → 访问设置」填写令牌，接口要求 operator 或更高权限。
