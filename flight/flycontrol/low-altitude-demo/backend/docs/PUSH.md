# 对外数据推送（UOM / 地方低空平台）

> 需求：向政府平台或 UOM 等推送数据。
> 实现：`app/integrations/`（适配层 + 发件箱 + 签名客户端） + `app/services/push_service.py` + `app/routers/push.py`。

---

## 1. 数据流

```
运行态（去重后的态势 / 当前程序 / 气象）
        │  collect()   按频率与变化量采集
        ▼
   报文适配层  integrations/uom_adapter.py     ← 所有字段映射集中在这里
        │
        ▼
   发件箱      integrations/outbox.py          ← SQLite 落库，断网不丢
        │  drain()   指数退避重试
        ▼
   签名客户端  integrations/uom_client.py      ← HMAC-SHA256 + HTTP
        │
        ▼
   政府平台 / UOM（演示时用 tools/mock_uom_server.py 代替）
```

---

## 2. 推送内容

| 类型 | msgType | 触发 | 默认频率 |
| --- | --- | --- | --- |
| 实时态势 | `SURVEILLANCE` | 定时 | 每 5 秒一批（已去重） |
| 飞行程序 | `FLIGHT_PROGRAM` | 程序版本变化 | 事件驱动 |
| 气象 | `METEO` | 气象内容变化 | 事件驱动 |
| 测试/心跳 | `HEARTBEAT` | 手动 `/api/push/test` | — |

报文信封：

```json
{
  "msgId": "…（内容哈希，幂等键）",
  "msgType": "SURVEILLANCE",
  "sendTime": "2026-10-22T10:00:00+00:00",
  "source": {"system": "LOWA-SKY", "nodeId": "NODE-A"},
  "version": "1.1",
  "payload": {"count": 7, "tracks": [{"uasId": "...", "altMsl": 120, ...}]}
}
```

> 当前适配器和签名协议仅为演示约定，尚未依据对端正式规范验证。真实接入除字段和信封映射外，还需核对认证、传输安全、业务回执、重试幂等、数据来源及双方联调要求。

---

## 3. 可靠性设计

`dry-run` 不联网，但目前会把演示消息标记为已发送；切换到 HTTP 模式不会自动重放这些消息。HTTP 模式仅依据 HTTP 2xx 判断发送成功，不解析对方业务回执，因此“成功”不等于对方业务接收或正式对接验收通过。演示发件箱不应用作生产补传队列。

| 机制 | 做法 |
| --- | --- |
| 不丢数据 | 先写 `push_outbox`（SQLite），再发送 |
| 幂等 | `msgId = sha1(主题+节点+时间+内容)`，重复采集不会重复推送 |
| 重试 | 指数退避 2s → 4s → … → 60s；超过 `max_attempts`(8) 记 `dead` |
| 可重放 | `POST /api/push/requeue` 把 dead 消息放回队列 |
| 限流 | 态势按 `PUSH_TRACK_INTERVAL` 合并成批，避免刷爆对端 |
| 可观测 | `/api/push/status` 返回队列深度、成功/失败、平均延迟、最近错误 |

---

## 4. 配置

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `PUSH_ENABLED` | `true` | 总开关 |
| `PUSH_MODE` | `dry-run` | `dry-run` 不联网（本地演示）；`http` 真实发送 |
| `PUSH_ENDPOINT` | `http://127.0.0.1:8099/uom/v1/messages` | 对端地址 |
| `PUSH_APP_KEY` / `PUSH_APP_SECRET` | `demo-app` / `demo-secret` | 签名凭据（生产用密钥管理注入） |
| `PUSH_INTERVAL` | `2` | 发件箱轮询周期（秒） |
| `PUSH_TRACK_INTERVAL` | `5` | 态势推送间隔（秒） |
| `PUSH_BATCH` | `20` | 每轮最多发几条 |
| `OUTBOX_DB` | `push_outbox.db` | 发件箱数据库路径 |

---

## 5. 接口

```http
GET  /api/push/status     # 状态与统计
POST /api/push/flush      # 立即推送（忽略退避）
POST /api/push/test       # 发一条心跳测试报文
POST /api/push/requeue    # dead 消息重新入队
```

---

## 6. 本地联调（Mock 对端）

```powershell
cd flight\flycontrol\low-altitude-demo\backend

# 1) 启动模拟接收端（校验签名并落盘）
python tools\mock_uom_server.py --port 8099

# 2) 以真实发送模式启动后端
$env:PUSH_MODE="http"
$env:PUSH_ENDPOINT="http://127.0.0.1:8099/uom/v1/messages"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8082

# 3) 生成一些态势（可选）
.\.venv\Scripts\python.exe tools\sim_two_devices.py --frames 5

# 4) 查看结果
Invoke-RestMethod http://127.0.0.1:8082/api/push/status
Invoke-RestMethod http://127.0.0.1:8099/uom/v1/messages
```

模拟端会把每条报文写入 `tools/uom_received.jsonl`，并校验 `X-Signature`。
门户「数据看板 → 数据推送」面板可直接看到成功率、延迟、队列深度。

---

## 7. 测试

```powershell
pytest tests\test_push.py -q
```

覆盖：报文映射、信封与 msgId 幂等、HMAC 签名、发件箱去重/退避/dead/重放、
推送服务成功与失败路径、重复采集去重。
