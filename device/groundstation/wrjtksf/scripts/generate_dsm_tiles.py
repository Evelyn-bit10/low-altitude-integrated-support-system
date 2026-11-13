# scripts/generate_dsm_tiles.py
"""将 GeoTIFF DSM 转为 Web 墨卡托瓦片 (z/x/y.png)，供 Leaflet 叠加显示
   
   高德地图使用 GCJ-02 坐标系，而 TIFF 是 WGS-84。
   Leaflet 按 WGS-84 计算瓦片 x/y，但高德返回 GCJ-02 内容。
   因此 DSM 瓦片必须从 GCJ-02 坐标反算 WGS-84 后再采样，才能对齐底图。"""
import os, sys, math
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

try:
    import rasterio
except ImportError:
    print("请先安装: pip install rasterio Pillow")
    sys.exit(1)

# ========== 配置 ==========
TIF_PATH = r"c:\Users\14308\Desktop\ythwrj\重庆龙兴通用机场_DSM_20260618(1).tif"
OUT_DIR  = r"c:\Users\14308\Desktop\ythwrj\wrjtksf\drone_ground_station\offline_data\tiles\dsm"
TILE_SIZE = 256
MIN_ZOOM  = 14
MAX_ZOOM  = 18
MAX_WORKERS = 4

# GCJ-02 校正开关: True=将瓦片边界当作 GCJ-02 反算 WGS-84 采样（对齐高德底图），False=直接 WGS-84 采样
USE_GCJ_CORRECTION = True

# ========== GCJ-02 ↔ WGS-84 坐标转换 ==========
# 高德 / 国内图商使用 GCJ-02（火星坐标系），与 WGS-84 有 300-500m 偏移
# 瓦片生成时必须把 GCJ-02 → WGS-84 来对齐 TIFF

_A = 6378245.0
_EE = 0.00669342162296594323  # e²

def _is_out_of_china(lon, lat):
    return lon < 72.004 or lon > 137.8347 or lat < 0.8293 or lat > 55.8271

def _transform_lat(x, y):
    ret = -100.0 + 2.0*x + 3.0*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
    ret += (20.0*math.sin(y*math.pi) + 40.0*math.sin(y/3.0*math.pi)) * 2.0/3.0
    ret += (160.0*math.sin(y/12.0*math.pi) + 320.0*math.sin(y*math.pi/30.0)) * 2.0/3.0
    return ret

def _transform_lon(x, y):
    ret = 300.0 + x + 2.0*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
    ret += (20.0*math.sin(x*math.pi) + 40.0*math.sin(x/3.0*math.pi)) * 2.0/3.0
    ret += (150.0*math.sin(x/12.0*math.pi) + 300.0*math.sin(x/30.0*math.pi)) * 2.0/3.0
    return ret

def _delta(lon, lat):
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi
    magic = 1.0 - _EE * math.sin(rad) * math.sin(rad)
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1.0 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(rad) * math.pi)
    return dlon, dlat

def wgs84_to_gcj02(lon, lat):
    if _is_out_of_china(lon, lat):
        return lon, lat
    dlon, dlat = _delta(lon, lat)
    return lon + dlon, lat + dlat

def gcj02_to_wgs84(lon, lat):
    """Newton 迭代法: GCJ-02 → WGS-84（2-3 次迭代即可收敛到 <1m）"""
    if _is_out_of_china(lon, lat):
        return lon, lat
    w_lon, w_lat = lon, lat
    for _ in range(10):
        g_lon, g_lat = wgs84_to_gcj02(w_lon, w_lat)
        d_lon = g_lon - lon
        d_lat = g_lat - lat
        if abs(d_lon) < 1e-10 and abs(d_lat) < 1e-10:
            break
        w_lon -= d_lon
        w_lat -= d_lat
    return w_lon, w_lat

# ========== 颜色映射 ==========
def elevation_color(val, vmin, vmax):
    if vmax <= vmin:
        return (0, 0, 0, 0)
    t = np.clip((val - vmin) / (vmax - vmin), 0.0, 1.0)
    if t < 0.33:
        r = int(255 * t / 0.33)
        g = 180; b = 60
    elif t < 0.66:
        r = 255
        g = int(180 + 75 * (t - 0.33) / 0.33)
        b = int(60 - 60 * (t - 0.33) / 0.33)
    else:
        r = 255
        g = int(255 - 100 * (t - 0.66) / 0.34)
        b = 0
    a = int(130 + 60 * t)
    return (r, g, b, a)


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tile_bounds_lonlat(x, y, z):
    n = 2 ** z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


def generate_tile(src, z, x, y, vmin, vmax):
    # Leaflet 按 WGS-84 计算瓦片边界 → 但高德底图实际显示的是 GCJ-02
    # 因此将"名义 WGS-84 边界"当作 GCJ-02，反算 WGS-84 后再从 TIFF 采样
    lon_min, lat_min, lon_max, lat_max = tile_bounds_lonlat(x, y, z)

    if USE_GCJ_CORRECTION:
        # GCJ-02 → WGS-84（四个角，取外接矩形以保证覆盖）
        corners = [
            gcj02_to_wgs84(lon_min, lat_min),
            gcj02_to_wgs84(lon_min, lat_max),
            gcj02_to_wgs84(lon_max, lat_min),
            gcj02_to_wgs84(lon_max, lat_max),
        ]
        w_lon_min = min(c[0] for c in corners)
        w_lon_max = max(c[0] for c in corners)
        w_lat_min = min(c[1] for c in corners)
        w_lat_max = max(c[1] for c in corners)
    else:
        # 不做 GCJ-02 校正，直接按 WGS-84 使用瓦片边界
        w_lon_min, w_lat_min, w_lon_max, w_lat_max = lon_min, lat_min, lon_max, lat_max

    tif_bounds = src.bounds

    if (w_lon_max <= tif_bounds.left or w_lon_min >= tif_bounds.right or
        w_lat_max <= tif_bounds.bottom or w_lat_min >= tif_bounds.top):
        return None

    r0, c0 = src.index(w_lon_min, w_lat_max)
    r1, c1 = src.index(w_lon_max, w_lat_min)
    r0, r1 = sorted([max(0, int(r0)), min(src.height, int(r1) + 1)])
    c0, c1 = sorted([max(0, int(c0)), min(src.width, int(c1) + 1)])

    if r1 - r0 < 2 or c1 - c0 < 2:
        return None

    data = src.read(1, window=((r0, r1), (c0, c1)))
    nodata = src.nodata
    mask = (data == nodata) if nodata is not None else np.zeros_like(data, dtype=bool)

    img_data = data.astype(np.float32)
    img_data[mask] = np.nan
    img = Image.fromarray(img_data)
    img = img.resize((TILE_SIZE, TILE_SIZE), Image.BILINEAR)
    resampled = np.array(img)

    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    nan_mask = np.isnan(resampled)
    for rr in range(TILE_SIZE):
        for cc in range(TILE_SIZE):
            if nan_mask[rr, cc]:
                rgba[rr, cc] = (0, 0, 0, 0)
            else:
                rgba[rr, cc] = elevation_color(resampled[rr, cc], vmin, vmax)

    if (rgba[:, :, 3] == 0).all():
        return None

    out_dir = os.path.join(OUT_DIR, str(z), str(x))
    os.makedirs(out_dir, exist_ok=True)
    png_path = os.path.join(out_dir, f"{y}.png")
    Image.fromarray(rgba).save(png_path, 'PNG')
    return png_path


def main():
    print(f"读取 TIFF: {TIF_PATH}")
    with rasterio.open(TIF_PATH) as src:
        print(f"  尺寸: {src.width}x{src.height}, CRS: {src.crs}")
        data = src.read(1)
        nodata = src.nodata
        valid = data[data != nodata] if nodata is not None else data
        vmin, vmax = float(np.percentile(valid, 2)), float(np.percentile(valid, 98))
        print(f"  高程范围(2%-98%): {vmin:.1f} ~ {vmax:.1f} m")

        total = 0
        for z in range(MIN_ZOOM, MAX_ZOOM + 1):
            bounds = src.bounds
            if USE_GCJ_CORRECTION:
                # TIFF 是 WGS-84 → 转为 GCJ-02 来确定瓦片范围
                b_left, b_bottom = wgs84_to_gcj02(bounds.left, bounds.bottom)
                b_right, b_top = wgs84_to_gcj02(bounds.right, bounds.top)
            else:
                # 不转换，直接使用 WGS-84 边界确定瓦片范围
                b_left, b_bottom = bounds.left, bounds.bottom
                b_right, b_top = bounds.right, bounds.top
            x_min, y_min = lonlat_to_tile(b_left, b_top, z)
            x_max, y_max = lonlat_to_tile(b_right, b_bottom, z)
            limit = 2 ** z - 1
            x_min, x_max = max(0, x_min), min(limit, x_max)
            y_min, y_max = max(0, y_min), min(limit, y_max)

            tasks = [(x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)]
            if not tasks:
                continue
            print(f"  Zoom {z}: {len(tasks)} 瓦片 [x:{x_min}-{x_max}, y:{y_min}-{y_max}]", end='')

            cnt = 0
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                fut = {pool.submit(generate_tile, src, z, x, y, vmin, vmax): (x, y) for x, y in tasks}
                for f in as_completed(fut):
                    if f.result():
                        cnt += 1
            total += cnt
            print(f" → 生成 {cnt} 张")

    print(f"\n✅ 完成! 共 {total} 张瓦片 → {OUT_DIR}")


if __name__ == '__main__':
    main()
