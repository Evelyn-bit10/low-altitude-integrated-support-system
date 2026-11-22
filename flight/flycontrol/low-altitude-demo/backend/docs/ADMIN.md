# 运维、权限与资料管理

新增于 v1.6，补齐需求里"设备管理 / 路线管理 / 权限"三块，并加了运行时指标。

---

## 1. 运行时指标 `GET /api/metrics`

```
{
  "metrics": {
    "uptime_sec": 1284.5, "frames": 1280,
    "avg_frame_ms": 0.62,
    "frame_ms":      {"p50": 0.58, "p90": 0.71, "p99": 0.99, "max": 3.2},
    "candidates":    {"p50": 10, "p99": 34, "max": 52},
    "unique_tracks": {"now": 7, "p50": 7, "max": 7},
    "counters": {"matched": 5120, "created": 96, "duplicate": 12, ...}
  },
  "traffic": { ...去重统计... },
  "shadow":  { ...影子模式一致率... },
  "kalman":  {"tracks": 7, "sigma_mean": 7.45, "sigma_max": 8.45, "sigma_scale": 1.0}
}
```

用途：

| 场景 | 看哪个 |
| --- | --- |
| 演示"性能很好" | `frame_ms.p99` |
| 排障"为什么变慢" | `frames` vs `avg_frame_ms`，`candidates` 分布 |
| 判断门限是否异常 | `kalman.sigma_mean/max`（长时间无观测会膨胀） |
| 判断标定是否收敛 | `kalman.sigma_scale`（应偏离 1.0 才对） |

指标用固定长度环形缓冲（默认最近 600 帧），内存恒定。

---

## 2. RBAC 权限

内置三个角色，写操作才校验（GET 一律放行）：

| 角色 | 权限 |
| --- | --- |
| `viewer` | 只读 |
| `operator` | 业务写：生成程序、开关去重、发推送、上报态势 |
| `admin` | 全部，含设备台账 / 路线管理 / 影子模式开关 |

开启方式（默认关闭，演示不受影响）：

```powershell
$env:AUTH_ENABLED = "1"
$env:DEMO_TOKENS  = "tok-view:viewer,tok-op:operator,tok-admin:admin"   # 可选，不填用内置演示 token
```

请求时带 `X-Token` 头：

```bash
curl -X POST -H "X-Token: tok-admin" -H "Content-Type: application/json" \
     -d '{"name":"A站","source_key":"A-RID"}' http://127.0.0.1:8082/api/devices
```

实测：

| 请求 | 结果 |
| --- | --- |
| 无 token 写设备 | `401` |
| viewer 写设备 | `403` |
| admin 写设备 | `200` |
| 无 token 读指标 | `200` |

---

## 3. 设备管理台账 `/api/devices`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/devices` | 列表 |
| POST | `/api/devices` | 新增（`source_key` 唯一） |
| PUT | `/api/devices/{id}` | 修改 |
| DELETE | `/api/devices/{id}` | 删除 |

字段：`name` / `source_key`（报文里的 `source_node`）/ `kind`（rid/adsb/radar/camera）/
`sigma_m`（位置误差，会作为去重的观测噪声 R）/ `quality` / `status` / `note`。

数据落盘到 `backend/data/devices.json`，重启不丢。

---

## 4. 路线管理 `/api/routes`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/routes` | 列表 / 新增 |
| PUT/DELETE | `/api/routes/{id}` | 修改 / 删除 |

字段：`name` / `kind`（corridor 走廊、no_fly 禁飞、route 航路）/ `points[]`（x,y,z 米）/
`floor_agl` / `ceiling_agl` / `note`。落盘 `backend/data/routes.json`。

> 目前路线数据是独立台账，**尚未接入规划器**（规划器读的还是 `store.airspaces`）。
> 接线方式：在 `Store.snapshot()` 里把 `kind == "no_fly"` 的路线转成 `Airspace` 即可。

---

## 5. 航迹快照与恢复

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `DEDUP_SNAPSHOT` | `backend/data/tracks.json` | 快照路径 |
| `DEDUP_RESTORE` | `0` | 启动时是否从快照恢复 |

* 每 5 秒把可见航迹（含卡尔曼状态）原子写入快照；
* 开启恢复后，重启会把这些航迹装回引擎，超过 TTL 的自动丢弃。

用途：避免"重启后目标集体消失"，也让演示不用每次重新灌数据。

**注意**：这不是多节点方案。多节点共享状态需要外置存储（Redis/PG），
属于另一个量级的改造，本次没做。


---

## 6. 接入状态（重要）

| 功能 | 是否已接入引擎 |
| --- | --- |
| 设备台账 `sigma_m` | ✅ 已接入：`TrafficStore._make_engine()` 会把台账里的 σ 合并进 `source_sigmas`（台账优先于配置，离线的设备会被忽略） |
| 路线 `kind=no_fly` | ✅ 已接入：`Store.snapshot()` 会把它们转成 `Airspace` 并入限制空域，规划器下一帧生效 |
| 路线 `corridor` / `route` | ⬜ 仅台账登记，尚未参与规划 |

修改台账/路线后**需要重启服务或 `POST /api/traffic/reset`** 才对去重生效（引擎在创建时读取）。

> 注意：改了设备的 σ 会改变去重的门限，而门限是 RL 策略的输入特征之一
> （见 `docs/RL_DEDUP.md` 的"门限写进特征"），所以**策略的一致率会随之变化**。
> 这是预期行为，不是 bug。
