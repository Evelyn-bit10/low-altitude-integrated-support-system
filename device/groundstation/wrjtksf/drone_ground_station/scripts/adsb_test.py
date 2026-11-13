#!/usr/bin/env python3
"""
ADS-B 串口原始数据测试脚本
用法: python adsb_test.py [/dev/ttyUSB0] [921600]

在终端直接运行，打印接收到的原始报文 + rs1090 解码结果，
像日志那样显示心跳统计。
Ctrl+C 退出。
"""
import sys
import time
import re
import serial

# ---- rs1090 ----
try:
    import rs1090
    HAS_RS1090 = True
except (ImportError, OSError) as e:
    print(f"[!] rs1090 不可用: {e}")
    HAS_RS1090 = False

# ---- 参数 ----
PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 921600

# ============================================================
# 纯函数：解析一行 ADS-B 原始字符串
# ============================================================
def extract_hex(line: str) -> str | None:
    raw = line.strip().replace(" ", "")
    if not raw:
        return None
    m = re.search(r"([0-9A-Fa-f]{28})", raw)
    if not m:
        return None
    msg = m.group(1).upper()
    if len(msg) != 28 or not re.fullmatch(r"[0-9A-Fa-f]+", msg):
        return None
    first_byte = int(msg[0:2], 16)
    df = (first_byte >> 3) & 0x1F
    if df not in (17, 18):
        return None
    return msg


def describe(msg: str) -> str:
    """返回简短的类型描述"""
    tc_map = {
        1: "ID", 2: "ID", 3: "ID", 4: "ID",
        5: "位置(地表)", 6: "位置(地表)", 7: "位置(地表)", 8: "位置(地表)",
        9: "位置(空中)", 10: "位置(空中)", 11: "位置(空中)", 12: "位置(空中)",
        13: "位置(空中)", 14: "位置(空中)", 15: "位置(空中)", 16: "位置(空中)",
        17: "位置(空中)", 18: "位置(空中)",
        19: "速度(空中)", 20: "位置(空中)", 21: "位置(空中)", 22: "位置(空中)",
    }
    try:
        me_hex = msg[8:22]
        me_first = int(me_hex[:2], 16)
        tc = (me_first >> 3) & 0x1F
        return tc_map.get(tc, f"TC={tc}")
    except Exception:
        return "?"

# ============================================================
# 主逻辑
# ============================================================
def main():
    print(f"ADS-B 原始数据测试")
    print(f"  端口: {PORT}  |  波特率: {BAUD}  |  rs1090: {'✅' if HAS_RS1090 else '❌'}")
    print(f"  按 Ctrl+C 退出\n")

    ser = serial.Serial(PORT, BAUD, timeout=0.5, rtscts=False, dsrdtr=False)
    ser.reset_input_buffer()
    time.sleep(0.3)
    print(f"✅ 已连接 {PORT}\n")

    buf = b""
    total_lines = 0
    total_decoded = 0
    last_beat = time.time()
    beat_lines = 0
    start_time = time.time()

    try:
        while True:
            chunk = ser.read(4096)
            if chunk:
                buf += chunk
            else:
                # 数据断流计数（仅打印提示）
                continue

            # 拆行
            while True:
                nl = buf.find(b"\n")
                cr = buf.find(b"\r")
                if nl < 0 and cr < 0:
                    break
                sep = min(nl, cr) if nl >= 0 and cr >= 0 else (nl if nl >= 0 else cr)
                raw_line = buf[:sep]
                buf = buf[sep + 1:]

                if not raw_line:
                    continue
                try:
                    line = raw_line.decode("ascii", errors="ignore").strip()
                except Exception:
                    continue
                if not line:
                    continue

                total_lines += 1
                beat_lines += 1

                # 尝试解析
                hex_msg = extract_hex(line)
                if hex_msg:
                    icao = hex_msg[2:8]
                    desc = describe(hex_msg)

                    # rs1090 单帧解码
                    latlon = ""
                    if HAS_RS1090:
                        try:
                            decoded = rs1090.decode(hex_msg)
                            if isinstance(decoded, dict) and decoded.get("latitude") is not None:
                                lat = decoded["latitude"]
                                lon = decoded["longitude"]
                                alt = decoded.get("altitude", "?")
                                latlon = f"  lat={lat:.4f} lon={lon:.4f} alt={alt}"
                        except Exception:
                            pass

                    print(f"[{icao}] {desc:<12} {hex_msg}{latlon}")
                    total_decoded += 1
                else:
                    # 非 ADS-B 行：机顶盒调试输出等，静默
                    pass

            # 心跳统计
            now = time.time()
            if now - last_beat >= 5:
                elapsed = int(now - start_time)
                rate = beat_lines / (now - last_beat) if (now - last_beat) > 0 else 0
                print(f"--- 心跳: {beat_lines}行/5s ({rate:.0f}行/s) | 累计{total_lines}行 {total_decoded}解码 | 运行{elapsed}s ---")
                beat_lines = 0
                last_beat = now

    except KeyboardInterrupt:
        print("\n\n用户中断。")
    finally:
        ser.close()
        print(f"串口已关闭。累计 {total_lines} 行, {total_decoded} 条 ADS-B 报文。")

if __name__ == "__main__":
    main()
