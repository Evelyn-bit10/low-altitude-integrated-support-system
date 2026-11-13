# config.py
"""配置文件"""
import os

# ================== 多无人机默认配置 ==================
DEFAULT_DRONES = [
    {"id": "1", "name": "无人机 1", "emoji": "🚁", "port": "/dev/ttyUSB0", "baud": 57600}
]

# ================== 自动连接设置 ==================
AUTO_CONNECT_ON_START = False  # 启动时是否自动连接无人机

# ================== WeatherAPI配置 ==================
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")
WEATHER_UPDATE_INTERVAL = 300  # 5分钟更新一次

# ================== 地图配置 ==================
DEFAULT_MAP_CENTER = (29.5689, 106.5577)  # 默认地图中心（重庆）
AUTO_FIT_DISTANCE = 120  # 自动调整视野距离（米）
MAX_TRAIL_POINTS = 300  # 最大航迹点数

# ================== 串口配置 ==================
DEFAULT_BAUDRATE = 57600
BAUDRATE_OPTIONS = [9600, 19200, 38400, 57600, 115200]

# ================== Emoji选项 ==================
DRONE_EMOJIS = ["🚁", "🛩️", "🛸", "✈️", "🚀", "🪁", "🦅", "🎈"]

# ================== UI配置 ==================
WINDOW_SIZE = (1024, 768)
# 右侧面板最小宽度：用于控制右侧所有卡片/面板整体“框宽”
# 加宽以完整显示三个数据列（高度/电量/卫星）
RIGHT_PANEL_MIN_WIDTH = 420
LEFT_RIGHT_SPLIT_RATIO = (2, 1)  # 左右分割比例

# ================== SVG 图标配置 ==================
# 基于 config.py 所在目录的相对路径
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DRONE_SVG_PATH = os.path.join(_BASE_DIR, "photo", "无人机.svg")
GROUND_STATION_SVG_PATH = os.path.join(_BASE_DIR, "photo", "地面站.svg")

# ================== 邮件通知配置 ==================
# 注意：不要把真实密码/授权码提交到仓库。这里仅作占位，建议用环境变量覆盖。
SMTP_ENABLED = os.environ.get("SMTP_ENABLED", "false").lower() in ("1", "true", "yes")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")  # 使用环境变量注入授权码
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "true").lower() in ("1", "true", "yes")
SMTP_USE_STARTTLS = os.environ.get("SMTP_USE_STARTTLS", "false").lower() in ("1", "true", "yes")
MAIL_SENDER = os.environ.get("MAIL_SENDER", SMTP_USERNAME)
