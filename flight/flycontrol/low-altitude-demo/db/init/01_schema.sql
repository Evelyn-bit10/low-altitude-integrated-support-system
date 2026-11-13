-- ============================================================================
-- 低空动态起降飞行程序实时调整系统 —— 统一建表脚本(PostgreSQL + PostGIS)
-- 说明: 原文档将 MySQL 语法与 PostGIS 语法混用导致无法执行, 本脚本统一为
--       PostgreSQL 15 + PostGIS 3.3, 消除技术栈冲突。时序气象数据也从
--       InfluxDB 收敛到本库(简化部署, 见 lp_meteo_log)。
-- 执行: 由 postgis/postgis:15-3.3 镜像在首次启动时自动执行。
-- ============================================================================

-- 开启空间扩展(障碍物空间计算 / OAS 评价面求解)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- ---------------------------------------------------------------------------
-- 一、核心业务数据表
-- ---------------------------------------------------------------------------

-- 1. 低空起降点基础信息表
CREATE TABLE IF NOT EXISTS lp_airport_point (
    id             BIGSERIAL PRIMARY KEY,
    point_name     VARCHAR(100) NOT NULL,
    point_code     VARCHAR(50)  UNIQUE NOT NULL,
    lon            NUMERIC(12,7) NOT NULL,          -- 经度 WGS84
    lat            NUMERIC(12,7) NOT NULL,          -- 纬度 WGS84
    altitude       INTEGER NOT NULL,                -- 起降点标高 MSL(m)
    safe_radius    INTEGER DEFAULT 500,             -- 安全保护区半径(m)
    runway_heading NUMERIC(6,2) DEFAULT 0,          -- 主起降方向(真北向, 度)
    runway_dir     VARCHAR(20),
    max_type       VARCHAR(50),                     -- 适配最大机型
    status         SMALLINT DEFAULT 1,
    create_time    TIMESTAMPTZ DEFAULT now(),
    update_time    TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE lp_airport_point IS '低空起降点基础信息表';

-- 2. 起降点障碍物数据表(含 PostGIS 空间字段, 触发器自动同步 geom)
CREATE TABLE IF NOT EXISTS lp_obstacle (
    id            BIGSERIAL PRIMARY KEY,
    point_code    VARCHAR(50) NOT NULL,             -- 关联起降点编码
    obs_name      VARCHAR(100),
    obs_type      SMALLINT DEFAULT 1,               -- 1固定 2临时动态
    lon           NUMERIC(12,7),
    lat           NUMERIC(12,7),
    base_alt      INTEGER,                          -- 底部标高 MSL(m)
    top_alt       INTEGER,                          -- 顶部最高标高 MSL(m)
    radius        INTEGER DEFAULT 30,               -- 障碍物水平半径(m)
    buffer_radius INTEGER DEFAULT 60,               -- 安全缓冲区(m)
    valid_start   TIMESTAMPTZ,
    valid_end     TIMESTAMPTZ,
    status        SMALLINT DEFAULT 1,
    geom          geometry(POINTZ, 4326),           -- PostGIS 空间点(派生)
    create_time   TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE lp_obstacle IS '起降点障碍物数据表';

-- 空间字段自动同步触发器: 由 lon/lat/base_alt 派生三维点
CREATE OR REPLACE FUNCTION lp_obstacle_geom_sync() RETURNS trigger AS $$
BEGIN
    IF NEW.lon IS NOT NULL AND NEW.lat IS NOT NULL THEN
        NEW.geom = ST_SetSRID(ST_MakePoint(NEW.lon, NEW.lat, NEW.base_alt), 4326);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS lp_obstacle_geom_sync_trg ON lp_obstacle;
CREATE TRIGGER lp_obstacle_geom_sync_trg
    BEFORE INSERT OR UPDATE ON lp_obstacle
    FOR EACH ROW EXECUTE FUNCTION lp_obstacle_geom_sync();

-- 3. 飞行程序预案库表
CREATE TABLE IF NOT EXISTS lp_program_plan (
    id             BIGSERIAL PRIMARY KEY,
    point_code     VARCHAR(50) NOT NULL,
    plan_name      VARCHAR(100) NOT NULL,
    plan_type      SMALLINT,                         -- 1进场 2离场 3复飞
    wind_range     VARCHAR(50),                      -- 适配风向风速区间, 如 "0-10"
    visi_range     VARCHAR(50),                      -- 适配能见度区间, 如 "1000-99999"
    waypoint_json  TEXT,                             -- 航路点序列 JSON
    height_profile TEXT,                             -- 高度剖面
    is_default     SMALLINT DEFAULT 0,
    status         SMALLINT DEFAULT 1,
    create_time    TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE lp_program_plan IS '飞行程序预案库表';

-- 4. 程序发布记录表
CREATE TABLE IF NOT EXISTS lp_program_release (
    id              BIGSERIAL PRIMARY KEY,
    point_code      VARCHAR(50),
    plan_id         BIGINT,                          -- 关联预案ID, 动态生成为 0
    program_version VARCHAR(30) NOT NULL,
    program_type    SMALLINT,                        -- 1进场 2离场 3复飞
    waypoint_json   TEXT,
    height_profile  TEXT,
    risk_level      SMALLINT,                        -- 1低 2中 3高 4禁飞
    audit_user      VARCHAR(50),
    release_status  SMALLINT DEFAULT 1,              -- 1待审核 2已发布 3已驳回 4已失效
    notam_content   TEXT,
    release_time    TIMESTAMPTZ,
    create_time     TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE lp_program_release IS '飞行程序发布审计记录表';

-- 5. 民航规则参数表(超障余量/安全高度/权重等, 引擎运行时可读取)
CREATE TABLE IF NOT EXISTS lp_avi_rule (
    id          BIGSERIAL PRIMARY KEY,
    rule_key    VARCHAR(50) UNIQUE NOT NULL,
    rule_value  VARCHAR(100) NOT NULL,
    rule_desc   VARCHAR(200),
    rule_source VARCHAR(50) DEFAULT 'CCAR-97',
    status      SMALLINT DEFAULT 1
);
COMMENT ON TABLE lp_avi_rule IS '民航飞行程序规则参数表';

-- 6. 空域约束表(禁飞区/限飞区/临时活动)
CREATE TABLE IF NOT EXISTS lp_airspace (
    id           BIGSERIAL PRIMARY KEY,
    space_name   VARCHAR(100),
    poly_json    TEXT,                               -- 多边形经纬度 JSON: [[lon,lat],...]
    floor_alt    INTEGER,                            -- 下限 MSL(m)
    ceiling_alt  INTEGER,                            -- 上限 MSL(m)
    status       SMALLINT DEFAULT 1,
    create_time  TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE lp_airspace IS '空域约束表';

-- 7. 时序气象日志表(替代 InfluxDB, 秒级 append, 简化部署)
CREATE TABLE IF NOT EXISTS lp_meteo_log (
    id               BIGSERIAL PRIMARY KEY,
    point_code       VARCHAR(50) NOT NULL,
    wind_speed       NUMERIC(6,2),                   -- m/s
    wind_dir         NUMERIC(6,2),                   -- 度
    gust             NUMERIC(6,2),                   -- 阵风 m/s
    visibility       NUMERIC(8,2),                   -- 米
    cloud_base       INTEGER,                        -- 云底高 AGL(m)
    turbulence_level SMALLINT,
    wind_shear_level SMALLINT,
    temperature      NUMERIC(5,1),
    pressure         NUMERIC(7,2),
    ts               TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE lp_meteo_log IS '时序气象数据日志表';

-- ---------------------------------------------------------------------------
-- 二、RBAC 权限体系
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sys_user (
    id              BIGSERIAL PRIMARY KEY,
    username        VARCHAR(50) NOT NULL,
    password        VARCHAR(100) NOT NULL,           -- 加密密码
    real_name       VARCHAR(50),
    phone           VARCHAR(20),
    email           VARCHAR(100),
    avatar          VARCHAR(255),
    status          SMALLINT DEFAULT 1,
    dept_id         BIGINT DEFAULT 0,
    create_time     TIMESTAMPTZ DEFAULT now(),
    update_time     TIMESTAMPTZ DEFAULT now(),
    last_login_time TIMESTAMPTZ,
    UNIQUE (username)
);

CREATE TABLE IF NOT EXISTS sys_role (
    id          BIGSERIAL PRIMARY KEY,
    role_name   VARCHAR(50) NOT NULL,
    role_code   VARCHAR(50) NOT NULL,
    role_sort   INT DEFAULT 0,
    status      SMALLINT DEFAULT 1,
    remark      VARCHAR(255),
    create_time TIMESTAMPTZ DEFAULT now(),
    update_time TIMESTAMPTZ DEFAULT now(),
    UNIQUE (role_code)
);

CREATE TABLE IF NOT EXISTS sys_user_role (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    role_id     BIGINT NOT NULL,
    create_time TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS sys_menu (
    id          BIGSERIAL PRIMARY KEY,
    parent_id   BIGINT DEFAULT 0,
    menu_name   VARCHAR(50) NOT NULL,
    menu_type   SMALLINT NOT NULL,                   -- 1菜单 2按钮 3接口
    path        VARCHAR(255),
    component   VARCHAR(255),
    perms       VARCHAR(255),
    sort_order  INT DEFAULT 0,
    status      SMALLINT DEFAULT 1,
    create_time TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 三、索引
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_obstacle_point ON lp_obstacle(point_code);
CREATE INDEX IF NOT EXISTS idx_obstacle_geom  ON lp_obstacle USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_plan_point     ON lp_program_plan(point_code);
CREATE INDEX IF NOT EXISTS idx_release_point  ON lp_program_release(point_code);
CREATE INDEX IF NOT EXISTS idx_meteo_point_ts ON lp_meteo_log(point_code, ts DESC);
