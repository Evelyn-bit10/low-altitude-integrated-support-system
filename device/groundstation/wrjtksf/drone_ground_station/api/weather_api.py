import aiohttp
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any
import brotli  # 添加brotli支持

class WeatherAPI:
    """WeatherAPI.com 客户端封装"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.weatherapi.com/v1"
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建aiohttp会话，添加brotli支持"""
        if self._session is None or self._session.closed:
            # 创建支持brotli的会话
            connector = aiohttp.TCPConnector(force_close=False)
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={
                    'Accept-Encoding': 'gzip, deflate',  # 移除br，避免brotli编码
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
        return self._session
    
    async def get_current_weather(self, lat: float, lng: float) -> Dict[str, Any]:
        """
        根据经纬度获取当前天气
        
        Args:
            lat: 纬度
            lng: 经度
            
        Returns:
            包含天气信息的字典
        """
        session = await self._get_session()
        url = f"{self.base_url}/current.json"
        
        params = {
            "key": self.api_key,
            "q": f"{lat},{lng}",
            "aqi": "yes",  # 获取空气质量
            "lang": "zh"   # 添加中文支持
        }
        
        try:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    # 手动处理可能的内容编码
                    text = await self._decode_response(response)
                    try:
                        data = json.loads(text)
                        return self._parse_weather_data(data)
                    except json.JSONDecodeError as e:
                        raise Exception(f"JSON解析失败: {e}, 响应内容: {text[:200]}")
                else:
                    error_text = await response.text()
                    raise Exception(f"WeatherAPI 返回错误: {response.status} - {error_text}")
        except asyncio.TimeoutError:
            raise Exception("请求超时")
        except aiohttp.ClientError as e:
            raise Exception(f"网络请求失败: {str(e)}")
        except Exception as e:
            raise Exception(f"天气请求失败: {str(e)}")
    
    async def _decode_response(self, response) -> str:
        """手动解码响应，处理brotli编码"""
        content_encoding = response.headers.get('Content-Encoding', '')
        content_type = response.headers.get('Content-Type', '')
        
        # 读取原始数据
        data = await response.read()
        
        # 根据编码解码
        if 'br' in content_encoding:
            try:
                # 尝试brotli解码
                data = brotli.decompress(data)
            except Exception as e:
                print(f"Brotli解码失败: {e}, 尝试其他方法")
        
        # 根据内容类型解码文本
        if 'application/json' in content_type or 'text/' in content_type:
            try:
                return data.decode('utf-8')
            except UnicodeDecodeError:
                return data.decode('gbk', errors='ignore')
        else:
            return data.decode('utf-8', errors='ignore')
    
    def _parse_weather_data(self, data: Dict) -> Dict[str, Any]:
        """解析原始天气数据，增加容错"""
        try:
            current = data.get("current", {})
            location = data.get("location", {})
            
            # 获取空气质量数据
            air_quality = current.get("air_quality", {})
            
            # 处理可能缺失的字段
            return {
                "temperature": current.get("temp_c"),  # 温度（摄氏度）
                "humidity": current.get("humidity"),  # 湿度百分比
                "visibility": current.get("vis_km"),  # 能见度（公里）
                "precipitation": current.get("precip_mm"),  # 降水量（毫米）
                "wind_speed": current.get("wind_kph"),  # 风速（公里/小时）
                "wind_dir": current.get("wind_dir"),  # 风向
                "pressure": current.get("pressure_mb"),  # 气压（毫巴）
                "cloud": current.get("cloud"),  # 云量百分比
                "feelslike": current.get("feelslike_c"),  # 体感温度
                "uv": current.get("uv"),  # 紫外线指数
                "gust": current.get("gust_kph"),  # 阵风
                "condition": current.get("condition", {}).get("text", "未知"),  # 天气状况描述
                "condition_code": current.get("condition", {}).get("code"),  # 天气代码
                "condition_icon": current.get("condition", {}).get("icon"),  # 天气图标
                "air_quality": {
                    "co": air_quality.get("co"),
                    "no2": air_quality.get("no2"),
                    "o3": air_quality.get("o3"),
                    "so2": air_quality.get("so2"),
                    "pm2_5": air_quality.get("pm2_5"),
                    "pm10": air_quality.get("pm10"),
                    "us_epa_index": air_quality.get("us-epa-index"),
                    "gb_defra_index": air_quality.get("gb-defra-index")
                },
                "last_updated": current.get("last_updated"),  # 最后更新时间
                "location_name": f"{location.get('name', '未知')}, {location.get('country', '未知')}",  # 位置名称
                "localtime": location.get("localtime")  # 当地时间
            }
        except Exception as e:
            print(f"解析天气数据失败: {e}")
            # 返回基本结构
            return {
                "temperature": None,
                "humidity": None,
                "visibility": None,
                "precipitation": None,
                "condition": "数据解析失败",
                "location_name": "未知位置",
                "air_quality": {}
            }


class WeatherManager:
    """天气管理器，负责定时更新和缓存"""
    
    def __init__(self, api_key: str, update_interval: int = 300):  # 默认5分钟更新一次
        self.api = WeatherAPI(api_key)
        self.update_interval = update_interval  # 更新间隔（秒）
        self.last_data: Optional[Dict] = None
        self.last_update: Optional[datetime] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._retry_count = 0
        self._max_retries = 3
        
    async def get_weather(self, lat: float, lng: float, force_refresh: bool = False) -> Dict[str, Any]:
        """
        获取天气，如果缓存有效则返回缓存
        
        Args:
            lat: 纬度
            lng: 经度
            force_refresh: 是否强制刷新
            
        Returns:
            天气数据
        """
        now = datetime.now()
        
        # 检查缓存是否有效
        if (not force_refresh and 
            self.last_data is not None and 
            self.last_update is not None and 
            (now - self.last_update).total_seconds() < self.update_interval):
            return self.last_data
        
        # 获取最新数据
        retry_count = 0
        last_error = None
        
        while retry_count < self._max_retries:
            try:
                data = await self.api.get_current_weather(lat, lng)
                self.last_data = {
                    **data,
                    "timestamp": now.timestamp()
                }
                self.last_update = now
                self._retry_count = 0  # 重置重试计数
                return self.last_data
            except Exception as e:
                last_error = str(e)
                retry_count += 1
                self._retry_count = retry_count
                if retry_count < self._max_retries:
                    # 指数退避重试
                    wait_time = 2 ** retry_count
                    print(f"天气获取失败，{wait_time}秒后重试 ({retry_count}/{self._max_retries}): {last_error}")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"天气获取失败，已重试{self._max_retries}次: {last_error}")
        
        # 如果获取失败但有缓存，返回缓存的旧数据并标记错误
        if self.last_data is not None:
            self.last_data["error"] = last_error
            self.last_data["error_time"] = now.timestamp()
            return self.last_data
        
        # 完全没有数据，返回空字典
        return {
            "temperature": None,
            "humidity": None,
            "visibility": None,
            "precipitation": None,
            "condition": "获取失败",
            "location_name": "未知",
            "air_quality": {},
            "error": last_error
        }
    
    async def start_auto_update(self, lat: float, lng: float, callback=None):
        """
        启动自动更新
        
        Args:
            lat: 纬度
            lng: 经度
            callback: 更新回调函数
        """
        self._running = True
        self._task = asyncio.create_task(self._auto_update_loop(lat, lng, callback))
    
    async def _auto_update_loop(self, lat: float, lng: float, callback=None):
        """自动更新循环"""
        while self._running:
            try:
                data = await self.get_weather(lat, lng, force_refresh=True)
                if callback:
                    callback(data)
            except Exception as e:
                print(f"天气自动更新失败: {e}")
            
            # 等待下一次更新，但可以提前取消
            for _ in range(self.update_interval):
                if not self._running:
                    break
                await asyncio.sleep(1)
    
    async def stop_auto_update(self):
        """停止自动更新"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.api.close()
    
    def get_last_data(self) -> Optional[Dict]:
        """获取最后获取的天气数据"""
        return self.last_data