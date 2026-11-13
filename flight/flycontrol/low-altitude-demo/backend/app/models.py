"""SQLAlchemy ORM 模型(与 db/init/01_schema.sql 对齐, 不含 PostGIS 特有类型,
以便在无 PostGIS 的 SQLite 回退模式下同样可运行)。"""
from __future__ import annotations

from sqlalchemy import (DateTime, Float, ForeignKey, Integer,
                        Numeric, SmallInteger, String, Text, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LpAirportPoint(Base):
    __tablename__ = "lp_airport_point"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    point_name: Mapped[str] = mapped_column(String(100))
    point_code: Mapped[str] = mapped_column(String(50), unique=True)
    lon: Mapped[float] = mapped_column(Numeric(12, 7))
    lat: Mapped[float] = mapped_column(Numeric(12, 7))
    altitude: Mapped[int] = mapped_column(Integer)
    safe_radius: Mapped[int] = mapped_column(Integer, default=500)
    runway_heading: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    runway_dir: Mapped[str | None] = mapped_column(String(20), nullable=True)
    max_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    create_time = mapped_column(DateTime(timezone=True), server_default=func.now())
    update_time = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LpObstacle(Base):
    __tablename__ = "lp_obstacle"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    point_code: Mapped[str] = mapped_column(String(50))
    obs_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    obs_type: Mapped[int] = mapped_column(SmallInteger, default=1)
    lon: Mapped[float | None] = mapped_column(Numeric(12, 7), nullable=True)
    lat: Mapped[float | None] = mapped_column(Numeric(12, 7), nullable=True)
    base_alt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_alt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    radius: Mapped[int] = mapped_column(Integer, default=30)
    buffer_radius: Mapped[int] = mapped_column(Integer, default=60)
    valid_start = mapped_column(DateTime(timezone=True), nullable=True)
    valid_end = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    create_time = mapped_column(DateTime(timezone=True), server_default=func.now())


class LpAirspace(Base):
    __tablename__ = "lp_airspace"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    space_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    poly_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    floor_alt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ceiling_alt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    create_time = mapped_column(DateTime(timezone=True), server_default=func.now())


class LpAviRule(Base):
    __tablename__ = "lp_avi_rule"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_key: Mapped[str] = mapped_column(String(50), unique=True)
    rule_value: Mapped[str] = mapped_column(String(100))
    rule_desc: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rule_source: Mapped[str] = mapped_column(String(50), default="CCAR-97")
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


class LpProgramPlan(Base):
    __tablename__ = "lp_program_plan"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    point_code: Mapped[str] = mapped_column(String(50))
    plan_name: Mapped[str] = mapped_column(String(100))
    plan_type: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    wind_range: Mapped[str | None] = mapped_column(String(50), nullable=True)
    visi_range: Mapped[str | None] = mapped_column(String(50), nullable=True)
    waypoint_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    height_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[int] = mapped_column(SmallInteger, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    create_time = mapped_column(DateTime(timezone=True), server_default=func.now())


class LpProgramRelease(Base):
    __tablename__ = "lp_program_release"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    point_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    program_version: Mapped[str] = mapped_column(String(30))
    program_type: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    waypoint_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    height_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    audit_user: Mapped[str | None] = mapped_column(String(50), nullable=True)
    release_status: Mapped[int] = mapped_column(SmallInteger, default=1)
    notam_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_time = mapped_column(DateTime(timezone=True), nullable=True)
    create_time = mapped_column(DateTime(timezone=True), server_default=func.now())


class LpMeteoLog(Base):
    __tablename__ = "lp_meteo_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    point_code: Mapped[str] = mapped_column(String(50))
    wind_speed: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    wind_dir: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    gust: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    visibility: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    cloud_base: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turbulence_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    wind_shear_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    pressure: Mapped[float | None] = mapped_column(Numeric(7, 2), nullable=True)
    ts = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---- RBAC(演示阶段仅建表, 鉴权逻辑后续接入) ----
class SysUser(Base):
    __tablename__ = "sys_user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password: Mapped[str] = mapped_column(String(100))
    real_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    dept_id: Mapped[int] = mapped_column(Integer, default=0)
    create_time = mapped_column(DateTime(timezone=True), server_default=func.now())
    update_time = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login_time = mapped_column(DateTime(timezone=True), nullable=True)


class SysRole(Base):
    __tablename__ = "sys_role"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(String(50))
    role_code: Mapped[str] = mapped_column(String(50), unique=True)
    role_sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    create_time = mapped_column(DateTime(timezone=True), server_default=func.now())
    update_time = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SysUserRole(Base):
    __tablename__ = "sys_user_role"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer)
    role_id: Mapped[int] = mapped_column(Integer)
    create_time = mapped_column(DateTime(timezone=True), server_default=func.now())


class SysMenu(Base):
    __tablename__ = "sys_menu"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(Integer, default=0)
    menu_name: Mapped[str] = mapped_column(String(50))
    menu_type: Mapped[int] = mapped_column(SmallInteger)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    component: Mapped[str | None] = mapped_column(String(255), nullable=True)
    perms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    create_time = mapped_column(DateTime(timezone=True), server_default=func.now())
