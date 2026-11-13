#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GPS 数据读取与解析示例
串口：/dev/ttyS0，波特率 115200
解析 GGA 和 RMC 语句（支持 $GP 和 $GN 前缀），输出北京时间（UTC+8）和十进制经纬度。
"""

import serial
import time
import sys

# 串口配置
PORT = "/dev/ttyS0"
BAUDRATE = 115200
TIMEOUT = 1  # 读取超时（秒）

def parse_gga(data):
    """
    解析 $GPGGA 或 $GNGGA 语句
    $GxGGA,<1>,<2>,<3>,<4>,<5>,<6>,<7>,<8>,<9>,M,<10>,M,<11>,<12>*hh<CR><LF>
    <1> UTC 时间，格式 hhmmss.ss
    <2> 纬度，格式 ddmm.mmmm
    <3> 纬度半球，N/S
    <4> 经度，格式 dddmm.mmmm
    <5> 经度半球，E/W
    <6> 定位质量指示，0=无效，1=单点定位，2=差分定位
    ... 其他字段略
    """
    parts = data.split(',')
    if len(parts) < 7:
        return None

    utc_time = parts[1]          # hhmmss.ss
    lat_str = parts[2]           # ddmm.mmmm
    lat_dir = parts[3]
    lon_str = parts[4]           # dddmm.mmmm
    lon_dir = parts[5]
    quality = parts[6]           # 定位质量

    if quality == '0':
        # 无效定位，跳过
        return None

    # 转换时间
    if utc_time and '.' in utc_time:
        # 格式：125315.00
        try:
            hh = int(utc_time[0:2])
            mm = int(utc_time[2:4])
            ss = float(utc_time[4:])
        except ValueError:
            return None
        # 转换为北京时间（UTC+8）
        hh_bj = (hh + 8) % 24
        time_str = f"{hh_bj:02d}:{mm:02d}:{ss:06.3f}"
    else:
        time_str = ""

    # 转换纬度
    lat = convert_ddm_to_decimal(lat_str, lat_dir)
    lon = convert_ddm_to_decimal(lon_str, lon_dir)

    return {
        'type': 'GGA',
        'time': time_str,
        'latitude': lat,
        'longitude': lon,
        'quality': quality
    }

def parse_rmc(data):
    """
    解析 $GPRMC 或 $GNRMC 语句
    $GxRMC,<1>,<2>,<3>,<4>,<5>,<6>,<7>,<8>,<9>,<10>,<11>,<12>*hh<CR><LF>
    <1> UTC 时间，格式 hhmmss.ss
    <2> 状态，A=有效，V=无效
    <3> 纬度，格式 ddmm.mmmm
    <4> 纬度半球，N/S
    <5> 经度，格式 dddmm.mmmm
    <6> 经度半球，E/W
    <7> 地面速率（节）
    <8> 地面航向（度）
    <9> UTC 日期，格式 ddmmyy
    <10> 磁偏角（度）
    <11> 磁偏角方向，E/W
    <12> 模式指示，A=自主，D=差分，E=估算，N=无效
    """
    parts = data.split(',')
    if len(parts) < 10:
        return None

    status = parts[2]            # A=有效
    if status != 'A':
        # 无效定位，跳过
        return None

    utc_time = parts[1]          # hhmmss.ss
    date_str = parts[9]          # ddmmyy

    # 转换时间与日期
    if utc_time and '.' in utc_time:
        try:
            hh = int(utc_time[0:2])
            mm = int(utc_time[2:4])
            ss = float(utc_time[4:])
        except ValueError:
            return None
        hh_bj = (hh + 8) % 24
        time_str = f"{hh_bj:02d}:{mm:02d}:{ss:06.3f}"
    else:
        time_str = ""

    if date_str and len(date_str) == 6:
        try:
            dd = date_str[0:2]
            mm = date_str[2:4]
            yy = date_str[4:6]
            date_str = f"20{yy}-{mm}-{dd}"
        except:
            date_str = ""

    # 转换经纬度
    lat = convert_ddm_to_decimal(parts[3], parts[4])
    lon = convert_ddm_to_decimal(parts[5], parts[6])

    return {
        'type': 'RMC',
        'time': time_str,
        'date': date_str,
        'latitude': lat,
        'longitude': lon,
        'speed': parts[7],
        'course': parts[8]
    }

def convert_ddm_to_decimal(coord_str, direction):
    """
    将度分格式的经纬度转换为十进制
    coord_str: NMEA原始坐标字符串 (例如 3954.1234 或 11623.1234)
    direction: N/S/E/W
    """
    if not coord_str or not direction:
        return None
        
    try:
        # 找到小数点的位置
        dot_idx = coord_str.find('.')
        if dot_idx < 2:
            return None
            
        # 核心修复：小数点前两位以及后面的所有内容都是"分"
        # 小数点前两位之前的内容才是"度"
        deg = int(coord_str[:dot_idx-2])
        minutes = float(coord_str[dot_idx-2:])
        
        # 将 度 + 分/60 换算为纯十进制
        decimal = deg + (minutes / 60.0)
        
        # 如果是南半球或西半球，坐标为负数
        if direction in ('S', 'W'):
            decimal = -decimal
            
        return decimal
    except Exception as e:
        print(f"坐标解析异常: {e}")
        return None

def get_pi_gps_sync(port="/dev/ttyS0", baudrate=115200, timeout=1.5):
    """同步读取一次树莓派 GPS 位置（通过串口 NMEA）。

    依次尝试 GGA 和 RMC 语句，返回 (latitude, longitude) 或 (None, None)。
    在非 Linux / 无串口的环境中安全返回 (None, None)。
    
    如果主端口失败，会自动尝试树莓派常见的其他 GPS 端口。
    timeout: 每个端口组合的最大等待时间（秒），默认 1.5 秒。
    """
    import platform
    # 在树莓派上按优先级尝试多个常见端口
    if platform.system() == "Linux":
        ports_to_try = [port]
        # 如果主端口是默认值，扩展候选列表
        if port == "/dev/ttyS0":
            ports_to_try = [
                "/dev/ttyS0",      # GPIO 串口 (PL011/mini-UART)
                "/dev/ttyAMA0",    # 硬件串口 (RPi 3B/4B 等)
                "/dev/ttyUSB0",    # USB-TTL 串口模块
                "/dev/ttyACM0",    # USB CDC ACM 设备（部分 GPS 模块）
                "/dev/serial0",    # 符号链接，指向主串口
            ]
        # 去重保持顺序
        seen = set()
        ports_to_try = [p for p in ports_to_try if not (p in seen or seen.add(p))]
    else:
        ports_to_try = [port]
    
    # 也尝试不同波特率
    baudrates_to_try = [baudrate]
    if baudrate == 115200:
        baudrates_to_try = [115200, 9600]
    else:
        baudrates_to_try = [baudrate, 9600, 115200]
    baudrates_to_try = list(dict.fromkeys(baudrates_to_try))  # 去重保持顺序
    
    last_error = None
    for try_port in ports_to_try:
        # 快速跳过不存在的端口
        import os as _os
        if not _os.path.exists(try_port):
            continue
        for try_baud in baudrates_to_try:
            try:
                ser = serial.Serial(try_port, try_baud, timeout=0.3)
            except Exception as e:
                last_error = str(e)
                continue

            deadline = time.time() + timeout
            lat = lng = None
            try:
                while time.time() < deadline:
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    if not line.startswith("$"):
                        continue
                    data = None
                    if line.startswith("$GPGGA") or line.startswith("$GNGGA"):
                        data = parse_gga(line)
                    elif line.startswith("$GPRMC") or line.startswith("$GNRMC"):
                        data = parse_rmc(line)
                    if data and data.get("latitude") is not None and data.get("longitude") is not None:
                        lat, lng = data["latitude"], data["longitude"]
                        break
            except Exception:
                pass
            finally:
                try:
                    ser.close()
                except Exception:
                    pass
            
            if lat is not None and lng is not None:
                print(f"[GPS] 成功获取位置: {try_port} @ {try_baud} baud → {lat:.6f}, {lng:.6f}")
                return (lat, lng)

    if last_error:
        print(f"[GPS] 所有端口尝试失败，最后错误: {last_error}")
    return (None, None)


def main():
    # 打开串口
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=TIMEOUT)
        print(f"已打开串口 {PORT}，波特率 {BAUDRATE}")
    except Exception as e:
        print(f"无法打开串口 {PORT}: {e}")
        sys.exit(1)

    print("开始读取 GPS 数据... (按 Ctrl+C 退出)")

    try:
        while True:
            # 读取一行数据（以 $ 开头，以 \n 结尾）
            line = ser.readline().decode('ascii', errors='ignore').strip()
            if not line:
                continue
            # 只处理以 $ 开头的 NMEA 语句
            if line.startswith('$'):
                # 根据语句类型解析（支持 GP 和 GN 前缀）
                if line.startswith('$GPGGA') or line.startswith('$GNGGA'):
                    data = parse_gga(line)
                    if data:
                        print(f"[GGA] 时间(北京): {data['time']}, 纬度: {data['latitude']:.6f}, 经度: {data['longitude']:.6f}, 质量: {data['quality']}")
                elif line.startswith('$GPRMC') or line.startswith('$GNRMC'):
                    data = parse_rmc(line)
                    if data:
                        print(f"[RMC] 日期: {data['date']}, 时间(北京): {data['time']}, 纬度: {data['latitude']:.6f}, 经度: {data['longitude']:.6f}, 速度: {data['speed']}节, 航向: {data['course']}°")
                # 其他语句可以忽略或扩展
                else:
                    pass
    except KeyboardInterrupt:
        print("\n用户中断，程序退出")
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        ser.close()
        print("串口已关闭")

if __name__ == "__main__":
    main()
