-- ============================================================================
-- 低空动态起降飞行程序实时调整系统 —— 种子数据
-- 统一技术栈: PostgreSQL + PostGIS
-- ============================================================================

-- 1. 起降点(虚构演示垂直起降场, 跑道方向真北 0 度)
INSERT INTO lp_airport_point
    (point_name, point_code, lon, lat, altitude, safe_radius, runway_heading, runway_dir, max_type)
VALUES
    ('演示垂直起降场', 'LAC-DEMO', 120.0000000, 30.0000000, 60, 500, 0.00, '36/18', 'eVTOL');

-- 2. 障碍物(1固定 / 2临时动态)
--    lon/lat 依据 ENU 偏移换算: 东向米 -> lon+=x/96406.6 ; 北向米 -> lat+=y/111320
INSERT INTO lp_obstacle
    (point_code, obs_name, obs_type, lon, lat, base_alt, top_alt, radius, buffer_radius, status)
VALUES
    ('LAC-DEMO', '施工塔吊(动态)', 2, 120.0004149, 29.9838304, 60, 210, 25, 60, 0),
    ('LAC-DEMO', '高层建筑(固定)', 1, 120.0025932, 30.0035932, 60, 170, 40, 60, 1),
    ('LAC-DEMO', '通信铁塔(固定)', 1, 119.9948136, 30.0053899, 60, 220, 20, 60, 1),
    ('LAC-DEMO', '山地(固定)',      1, 119.9896273, 30.0008983, 60, 300, 200, 80, 1),
    ('LAC-DEMO', '高压线塔(固定)', 1, 120.0062236, 29.9973051, 60, 120, 30, 60, 1);

-- 3. 空域约束(临时限飞区, 起降场西北方向, 高度 60~400m MSL)
INSERT INTO lp_airspace (space_name, poly_json, floor_alt, ceiling_alt)
VALUES (
    '临时限飞区-NW',
    '[[119.9875528,30.0053899],[119.9958509,30.0053899],[119.9958509,30.0125763],[119.9875528,30.0125763]]',
    60, 400
);

-- 4. 民航规则参数(引擎运行时可读取; 值为演示默认值, 生产需按 CCAR-97/PANS-OPS 标定)
INSERT INTO lp_avi_rule (rule_key, rule_value, rule_desc, rule_source) VALUES
    ('MOC_APPROACH',      '75',  '进近超障余度 MOC(m)',              'PANS-OPS/CCAR-97'),
    ('MOC_DEPARTURE',     '90',  '离场超障余度 MOC(m)',              'PANS-OPS/CCAR-97'),
    ('MSA_MARGIN',        '300', '最低安全高度 MSA 附加余度(m)',      'CCAR-97'),
    ('OAS_HALF_WIDTH0',   '100', 'OAS 评价面入口半宽(m)',            'PANS-OPS'),
    ('OAS_SPREAD',        '0.15','OAS 评价面横向扩展率',             'PANS-OPS'),
    ('OAS_GLIDESLOPE_DEG','5.7', '进近下滑角(度)',                  'PANS-OPS'),
    ('OAS_FINAL_DIST',   '1500','最终进近评价面长度(m)',            'PANS-OPS'),
    ('RISK_W_OBSTACLE',   '0.45','风险权重-障碍物',                  'DEMO'),
    ('RISK_W_METEO',      '0.35','风险权重-气象',                    'DEMO'),
    ('RISK_W_AIRSPACE',   '0.20','风险权重-空域',                    'DEMO'),
    ('RISK_TH_SAFE',      '20',  '风险阈值-低风险上限(分)',          'DEMO'),
    ('RISK_TH_NORMAL',    '40',  '风险阈值-中风险上限(分)',          'DEMO'),
    ('RISK_TH_WARNING',   '70',  '风险阈值-高风险上限(分)',          'DEMO');

-- 5. 默认进近预案(用于"预案优先切换"模式演示)
INSERT INTO lp_program_plan
    (point_code, plan_name, plan_type, wind_range, visi_range, waypoint_json, height_profile, is_default)
VALUES (
    'LAC-DEMO', '标准南向进近预案', 1, '0-8', '1000-99999',
    '[{"x":0,"y":-1500,"z":180},{"x":0,"y":-800,"z":100},{"x":0,"y":0,"z":0}]',
    '[{"dist":0,"alt":180},{"dist":700,"alt":100},{"dist":1500,"alt":0}]',
    1
);

-- 6. RBAC 默认账号与角色
--    演示阶段密码列以 {demo} 前缀明文占位; 生产必须替换为 bcrypt/argon2 哈希。
INSERT INTO sys_user (username, password, real_name, email) VALUES
    ('admin', '{demo}Admin@123', '系统管理员', 'admin@demo.local');

INSERT INTO sys_role (role_name, role_code, role_sort, remark) VALUES
    ('超级管理员',   'super_admin', 1, '全部权限'),
    ('运维管理员',   'ops_admin',   2, '环境数据与设备运维'),
    ('审核人员',     'auditor',     3, '程序审核发布'),
    ('普通操作员',   'operator',    4, '日常监控');

INSERT INTO sys_user_role (user_id, role_id)
SELECT u.id, r.id FROM sys_user u, sys_role r WHERE u.username='admin' AND r.role_code='super_admin';

INSERT INTO sys_menu (parent_id, menu_name, menu_type, path, component, perms, sort_order) VALUES
    (0, '程序监控', 1, '/program',   'ProgramView',   'program:view',   1),
    (0, '预案管理', 1, '/plan',      'PlanView',      'plan:view',      2),
    (0, '障碍物管理',1,'/obstacle',  'ObstacleView',  'obstacle:view',  3),
    (0, '系统管理', 1, '/system',    'SystemView',    'system:view',    4);
