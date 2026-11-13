# utils/coordinates.py
"""坐标转换工具"""
import math

def wgs84_to_gcj02(lat, lng):
    """
    WGS84坐标系转GCJ02坐标系（火星坐标系）
    
    Args:
        lat: WGS84纬度
        lng: WGS84经度
        
    Returns:
        (gcj_lat, gcj_lng): GCJ02坐标
    """
    if lat is None or lng is None:
        return lat, lng
        
    # 判断是否在中国境内
    def out_of_china(lat, lng):
        if lng < 72.004 or lng > 137.8347:
            return True
        if lat < 0.8293 or lat > 55.8271:
            return True
        return False
    
    # 如果不在中国境内，直接返回
    if out_of_china(lat, lng):
        return lat, lng
    
    a = 6378245.0
    ee = 0.00669342162296594323
    pi = 3.14159265358979323846
    
    def transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * pi) + 20.0 * math.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * pi) + 40.0 * math.sin(y / 3.0 * pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * pi) + 320 * math.sin(y * pi / 30.0)) * 2.0 / 3.0
        return ret
    
    def transform_lng(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * pi) + 20.0 * math.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * pi) + 40.0 * math.sin(x / 3.0 * pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * pi) + 300.0 * math.sin(x / 30.0 * pi)) * 2.0 / 3.0
        return ret
    
    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * pi)
    
    return lat + dlat, lng + dlng


def gcj02_to_wgs84(lat, lng):
    """
    GCJ02坐标系转WGS84坐标系（Newton 迭代法，精度 < 1m）
    
    Args:
        lat: GCJ02纬度
        lng: GCJ02经度
        
    Returns:
        (wgs_lat, wgs_lng): WGS84坐标
    """
    if lat is None or lng is None:
        return lat, lng
        
    w_lat, w_lng = lat, lng
    for _ in range(10):
        g_lat, g_lng = wgs84_to_gcj02(w_lat, w_lng)
        d_lat = g_lat - lat
        d_lng = g_lng - lng
        if abs(d_lat) < 1e-10 and abs(d_lng) < 1e-10:
            break
        w_lat -= d_lat
        w_lng -= d_lng
    return w_lat, w_lng