# 低空起降点系统 · 统一数据接口契约 (v1.1)

> 本文件是 `communication/`(通讯与态势)与 `flycontrol/`(飞行程序规划)两个项目之间的**统一接口规范**。
> 目标:两个项目读写同一套数据模型,实现**双向同步** —— 环境/程序数据由 `flycontrol` 下发,
> 实时飞行器态势由 `communication` 回传,为后期接入真实飞机与指挥起降打基础。

---

## 1. 总原则

1. **统一坐标系**:跨项目传输一律使用 **WGS84 经纬度 + 海拔(MSL, 米)**。各项目内部仍可用本地 ENU 平面
   (x 东向, y 北向, z 相对起降点标高/AGL),但**边界(网络接口)必须转成经纬度 + MSL**。
2. **统一命名**:字段一律 **snake_case**、SI 单位(米、米/秒、度、hPa、℃)。
3. **统一消息封装**:所有报文采用「消息头 + 载荷」结构(见 §4),与 communication 现有 CAAC 风格一致。
4. **单一数据源(Source of Truth)**:
   - 起降点 / 障碍物 / 空域 / 气象 / 飞行程序 → 以 `flycontrol` 为准(它已有数据库)。
   - 实时飞行器态势 / C2 / RID → 以 `communication` 为准(它负责接收与仿真)。

---

## 2. 坐标换算公式(两边必须完全一致)

```text
M_PER_DEG_LAT = 111320.0
mpdl(lat)     = M_PER_DEG_LAT * cos(lat * π/180)

ENU -> 经纬度:
  lon = ref_lon + x / mpdl(ref_lat)
  lat = ref_lat + y / M_PER_DEG_LAT
  alt(MSL) = ref_alt + z            # z 为相对起降点标高的 AGL

经纬度 -> ENU:
  x = (lon - ref_lon) * mpdl(ref_lat)
  y = (lat - ref_lat) * M_PER_DEG_LAT
  z = alt(MSL) - ref_alt
```

参考点 `(ref_lat, ref_lon, ref_alt)` 即起降点(机场)的经纬度与标高。该公式与 `flycontrol` 的
`engines/geometry.py` 完全一致,`shared/interface.js`、`shared/interface.py` 均已镜像。

---

## 3. 统一实体模型 (canonical)

### 3.1 Airport 起降点
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | string | 起降点编号,如 `LAC-DEMO` |
| `name` | string | 名称 |
| `lat` / `lon` | float | 经纬度(度) |
| `elevation` | float | 起降点标高 MSL(米) |
| `safe_radius` | float | 安全半径(米) |
| `runway_heading` | float | 主起降方向(真北, 度) |

### 3.2 Obstacle 障碍物
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 唯一编号(统一转字符串) |
| `name` | string | 名称 |
| `type` | string | `fixed` 固定 / `dynamic` 动态(塔吊等) |
| `lat` / `lon` | float | 中心点经纬度 |
| `base_msl` | float | 底部海拔 MSL(米) |
| `top_msl` | float | 顶部海拔 MSL(米) |
| `radius` | float | 水平半径(米) |
| `buffer` | float | 安全缓冲半径(米) |
| `active` | bool | 是否生效 |

### 3.3 Airspace 空域 / 电子围栏
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 编号 |
| `name` | string | 名称 |
| `polygon` | `[[lat,lon],...]` | 顶点(经纬度, 可顺时针/逆时针) |
| `floor_msl` | float | 下限海拔 MSL(米) |
| `ceiling_msl` | float | 上限海拔 MSL(米) |
| `active` | bool | 是否生效 |

### 3.4 Meteo 气象
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `timestamp` | string | ISO8601 |
| `wind_speed` | float | 风速 m/s |
| `wind_dir` | float | 风向(度) |
| `gust` | float | 阵风 m/s |
| `visibility` | float | 能见度(米) |
| `cloud_base_agl` | float | 云底高 AGL(米) |
| `turbulence` | int | 湍流 1~4 |
| `wind_shear` | int | 风切变 1~4 |
| `temperature` | float | 温度 ℃ |
| `dew_point` | float | 露点 ℃ |
| `pressure` | float | 气压 hPa |

### 3.5 Traffic 实时飞行器
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 呼号,如 `UAS-2024-0001` |
| `model` | string | 机型 |
| `reg_no` | string | 实名登记号 |
| `ua_id` | string | 唯一产品识别码 |
| `phase` | string | `APPROACH/DEPARTURE/HOVER/CRUISE/STANDBY/LANDED` |
| `lat` / `lon` | float | 当前经纬度 |
| `alt_msl` | float | 当前海拔 MSL(米) |
| `speed` | float | 地速 m/s |
| `heading` | float | 航向(度, 北为0顺时针) |
| `vertical_speed` | float | 升降率 m/s |
| `battery_pct` | int | 电量 % |
| `link_quality` | int | 链路质量 1~5 |
| `emergency` | bool | 紧急状态 |
| `rid_lost` | bool | RID 是否丢失 |
| `route` | `[{lat,lon,alt_msl}]` | 预设航路(经纬度+MSL) |
| `ts` | string | **观测时刻** ISO8601(不是收到时刻;缺省由服务端收到时间补齐) |
| `source_node` | string | 上报节点/设备,如 `NODE-A` / `RID-7A21`;缺省 `LOCAL` |
| `quality` | float 0~1 | 该源可信度(RID 0.8 / ADS-B 0.6 / 雷达 0.4),缺省 0.6 |
| `msg_id` | string | 幂等键,防同一报文被重复转发;缺省按 `ua_id+ts+经纬度` 哈希生成 |
| `sigma` | float | 该源位置误差 σ(米),可选;缺省按 `source_node` 查表(默认 20,下限 8) |

### 3.6 Program 飞行程序(进近/离场航路)
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `type` | string | `arrival` / `departure` / `missed` |
| `version` | string | 版本号 |
| `source` | string | `static` / `plan` / `dynamic` |
| `plan_id` | int | 预案ID(动态生成为 0) |
| `direction` | string | 进出场方向 `N/NE/E/SE/S/SW/W/NW`（v1.1 新增） |
| `std_name` | string | 标准程序名，如 `ARR-S` / `DEP-NE` |
| `waypoints` | `[{lat,lon,alt_msl,speed}]` | 主航路点 |
| `miss_approach` | `[{lat,lon,alt_msl,speed}]` | 复飞航路点 |

### 3.7 Snapshot 统一快照(核心同步接口的载荷)
```jsonc
{
  "schema_version": "1.0",
  "frame": "WGS84",
  "altitude_ref": "MSL",
  "generated_at": "2026-...ISO8601...",
  "airport":    { /* Airport */ },
  "obstacles":  [ /* Obstacle */ ],
  "airspaces":  [ /* Airspace */ ],
  "meteo":      { /* Meteo */ },
  "program":    { /* Program */ } | null,
  "traffic":    [ /* Traffic */ ]
}
```

---

### 3.8 Traffic 去重输出（`GET /api/traffic`）

同一架飞机可能被多个设备/节点同时看到。后端在 `ingest` 之后做**同一性判定与去重**，
`/api/traffic` 与 `/api/sync/snapshot` 输出的都是**去重后的唯一航迹**，下游不得再做二次去重。

在 3.5 的字段基础上，额外携带：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `global_id` | string | 去重后的全局航迹 ID（稳定标识） |
| `sources` | string[] | 参与融合的来源列表,如 `["A-RID","B-RID"]` |
| `source_ids` | object | `{来源: 该源本地 ID}`，用于追溯原始报文 |
| `confidence` | float 0~1 | 融合置信度（多源一致则高） |
| `merged` | bool | 是否由多源融合而来 |
| `callsign` | string | 主源的原始呼号（供界面展示；`id` 才是唯一键） |

判定规则（实现见 `backend/app/services/dedup.py`）：

1. 强正证据：`ua_id` 相同 → 同一架；`reg_no` 相同 → 同一架。
2. **强负证据**：双方都有 `ua_id` 且不同 → 一定不是同一架，几何再接近也不合并。
3. 弱证据（仅用于缺 ID 的情况）：水平距离 ≤ `v_max·Δt + 3σ`、高差 ≤ 30 m、航向差 ≤ 30°。
4. 未确认的无 ID 新航迹处于 `TENTATIVE`，**不对外输出**；连续两帧命中才确认。

---

## 4. 统一消息封装(报文信封)

所有 C2 / RID / 业务报文统一为:

```jsonc
{
  "protocol": "CAAC-UTM-C2/1.0",           // 或 CAAC-RID-BROADCAST/1.0
  "messageHeader": {
    "messageType": "ATC_CLEARANCE_LAND",     // 见 communication README 报文类型表
    "messageId": "MSG-...",
    "sender": "LAC-DEMO",
    "receiver": "UAS-2024-0001",
    "timestamp": "2026-...ISO8601..."
  },
  "payload": { /* 业务载荷 */ }
}
```

- 飞行器→起降点:`RID_BROADCAST / HEARTBEAT / POSITION_REPORT / TAKEOFF_REQUEST / LANDING_REQUEST / C2_ACK`
- 起降点→飞行器:`ATC_CLEARANCE_TAKEOFF / ATC_CLEARANCE_LAND / HOLD_INSTRUCTION / GO_AROUND / WEATHER_BROADCAST / OBSTACLE_ALERT / LINK_CHECK / C2_FREE_TEXT`

`/api/traffic/ingest` 同时接受「裸数组」「单个对象」「带信封的对象」三种形式,统一按本节规范解析。

---

## 5. 字段映射表(旧 → 统一)

### 5.1 communication → canonical
| communication 字段 | canonical 字段 | 换算 |
| --- | --- | --- |
| 障碍物 `height`(顶高 AGL) | `top_msl` | `top_msl = airport.elevation + height` |
| 障碍物 `radius` | `radius` | 直接对应 |
| 障碍物 `type`(building/tower/…) | `type` | 全部 → `fixed`(如需动态另行标注) |
| 障碍物 `x, y`(ENU) | `lat, lon` | 用 §2 公式 |
| 气象 `wind` | `wind_speed` | 直接 |
| 气象 `windDir` | `wind_dir` | 直接 |
| 气象 `ceiling` | `cloud_base_agl` | 直接 |
| 气象 `temp / dewPoint / qnh` | `temperature / dew_point / pressure` | 直接 |
| 气象(缺 `turbulence/wind_shear`) | `turbulence/wind_shear` | 默认 `1` |
| 围栏 `fencePoly`[{x,y}] | 空域 `polygon`[lat,lon] | `floor_msl=elevation`, `ceiling_msl=elevation+500` |
| 飞行器 `alt`(AGL) | `alt_msl` | `alt_msl = elevation + alt` |
| 飞行器 `regNo / uaId / vs` | `reg_no / ua_id / vertical_speed` | 直接 |

### 5.2 flycontrol → canonical
| flycontrol 字段 | canonical 字段 | 换算 |
| --- | --- | --- |
| 障碍物 `obs_type`(1/2) | `type` | 1→`fixed`, 2→`dynamic` |
| 障碍物 `top_agl` | `top_msl` | `top_msl = elevation + top_agl` |
| 障碍物 `base_agl` | `base_msl` | `base_msl = elevation + base_agl` |
| 障碍物 `id`(int) | `id` | 转字符串 |
| 气象 `wind_speed/wind_dir/cloud_base` | 同名 | 直接(`cloud_base`→`cloud_base_agl`) |
| 空域 `floor_agl/ceiling_agl` | `floor_msl/ceiling_msl` | `+ elevation` |
| 航路点 `Waypoint{x,y,z,speed}` | `waypoints[{lat,lon,alt_msl,speed}]` | §2 公式 |

---

## 6. 同步方向与接口

| 方向 | 数据 | 接口 |
| --- | --- | --- |
| flycontrol → communication | 起降点/障碍物/空域/气象/飞行程序/交通 | `GET /api/sync/snapshot` |
| communication → flycontrol | 实时飞行器态势 | `POST /api/traffic/ingest`（服务端去重后落库） |
| 查询当前交通 | 飞行器态势 | `GET /api/traffic`（去重后） |
| 去重统计 | 输入/输出条数 | `GET /api/traffic/stats` |

- 快照每 ~2s 由 flycontrol 调度刷新;communication 前端启动时拉取一次,此后可周期性拉取。
- 交通态势无持久化要求时可仅存内存(演示),生产需落库 `lp_traffic`(见 §7 扩展建议)。

---

## 7. 后期真实接入建议

1. 新增 `lp_traffic` 表持久化飞行器态势(带 `ts` 时间戳 + 超时失效),替换当前内存存储。
2. `communication` 的模拟 `generateWeather`/`receiveRid` 替换为真实气象站与 RID 广播接收器,报文走 §4 信封。
3. 增加鉴权(TLS + 签名 + 时间戳防重放),接入 UTM/USSP 数据接口与北斗短报文备份链路。
4. 将 `shared/interface.js` / `shared/interface.py` 抽为独立包,由 schema.json 驱动代码生成,避免两语言实现漂移。
