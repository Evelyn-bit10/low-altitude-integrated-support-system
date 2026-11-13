# mock_drone.py
"""无人机 MAVLink 信号模拟器"""
import time
import math
from pymavlink import mavutil

# 1. 连接到虚拟串口的“无人机端” (假设是 COM8)
PORT = 'COM8'
BAUDRATE = 57600

print(f"🔄 正在连接到 {PORT}...")
try:
    master = mavutil.mavlink_connection(PORT, baud=BAUDRATE)
    print(f"✅ 成功打开 {PORT}，开始发送模拟数据！")
except Exception as e:
    print(f"❌ 无法打开串口 {PORT}: {e}")
    exit(1)

# 初始坐标 (假设基准位置)
base_lat = 29.532028
base_lng = 106.604093
alt = 50.0
battery = 100.0
angle = 0.0

# 记录开机时间，用于计算 time_boot_ms
start_time = time.time()

while True:
    try:
        # 1. 发送心跳包
        master.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_QUADROTOR,
            mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
            0, 0, 0
        )

        # 模拟无人机绕圈飞行
        angle += 0.03
        current_lat = base_lat + math.sin(angle) * 0.001
        current_lng = base_lng + math.cos(angle) * 0.001
        current_alt = alt + math.sin(angle * 2) * 5.0
        battery = max(0.0, battery - 0.05)

        # 计算系统启动以来的毫秒数 (uint32_t 安全)
        time_boot_ms = int((time.time() - start_time) * 1000)

        # 2. 发送全局位置信息
        master.mav.global_position_int_send(
            time_boot_ms,             
            int(current_lat * 1e7),
            int(current_lng * 1e7),
            int(current_alt * 1000),
            int(current_alt * 1000),
            0, 0, 0, 0                
        )

        # 3. 发送 GPS 状态 
        time_usec = int(time.time() * 1e6)
        master.mav.gps_raw_int_send(
            time_usec,  
            3,                        # 3D定位
            int(current_lat * 1e7),
            int(current_lng * 1e7),
            int(current_alt * 1000),
            0, 0, 0, 0,
            14                        # 模拟14颗卫星可见
        )

        # 4. 发送系统状态 (修正：严格按照 13 个参数发送)
        master.mav.sys_status_send(
            0,              # onboard_control_sensors_present
            0,              # onboard_control_sensors_enabled
            0,              # onboard_control_sensors_health
            0,              # load (cpu load)
            12000,          # voltage_battery (mV，也就是 12V)
            -1,             # current_battery (-1 表示未测量)
            int(battery),   # battery_remaining (剩余电量百分比 0-100)
            0,              # drop_rate_comm
            0,              # errors_comm
            0,              # errors_count1
            0,              # errors_count2
            0,              # errors_count3
            0               # errors_count4
        )

        print(f"📡 已发送 -> Lat:{current_lat:.6f} Lng:{current_lng:.6f} Alt:{current_alt:.1f}m Bat:{int(battery)}%")
        time.sleep(0.5) 

    except KeyboardInterrupt:
        print("\n⏹️ 模拟器已停止")
        break