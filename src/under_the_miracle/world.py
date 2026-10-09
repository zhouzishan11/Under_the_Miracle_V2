"""世界底层：地形、气候、植被与动物。

这里只描述"环境条件"——玩家能改变的也只有这些。
世界本身并不知道什么是文明，它只负责让生命有可能活下去。
"""
from __future__ import annotations

import numpy as np
from PIL import Image


def _value_noise(rng: np.random.Generator, h: int, w: int, res: int) -> np.ndarray:
    """在 res x res 的粗网格上取随机值，再平滑放大到 (h, w)。"""
    res = max(2, int(res))
    grid = rng.random((res, res)).astype(np.float32)
    img = Image.fromarray((grid * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(img, dtype=np.float32) / 255.0


def fbm(rng: np.random.Generator, h: int, w: int, octaves: int = 5, base: int = 3) -> np.ndarray:
    """分形噪声，用来生成自然的大陆轮廓。"""
    out = np.zeros((h, w), np.float32)
    amp, total, res = 1.0, 0.0, base
    for _ in range(octaves):
        out += amp * _value_noise(rng, h, w, res)
        total += amp
        amp *= 0.5
        res *= 2
    return out / total


def _mix(a: np.ndarray, b: np.ndarray, f: np.ndarray) -> np.ndarray:
    return a * (1.0 - f) + b * f


class World:
    """一片空白的天地：有形状，却没有生命。"""

    def __init__(self, width: int = 120, height: int = 80, seed: int = 1):
        self.w = width
        self.h = height
        self.tick = 0
        self.sea_level = 0.42
        rng = np.random.default_rng(seed)
        self._rng = rng

        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        self.yy, self.xx = yy, xx

        # ---- 地形：中央一块大陆，四周是海 ----
        base = fbm(rng, height, width, 5, 3)
        base = (base - base.min()) / (np.ptp(base) + 1e-6)
        nx = (xx - width * 0.5) / (width * 0.5)
        ny = (yy - height * 0.5) / (height * 0.5)
        d = np.sqrt(nx * nx * 0.85 + ny * ny)
        edge = np.clip(1.0 - d * 0.78, 0.0, 1.0)
        self.elevation = np.clip(base * 0.55 + edge * 0.62 - 0.06, 0.0, 1.0).astype(np.float32)

        # ---- 低处天然蓄着几片湖水：世界是空白的，但不是死的 ----
        self._carve_lakes(rng, yy, xx)

        # ---- 温度：赤道最热，两极最冷，高处更冷 ----
        heat = 1.0 - np.abs(yy / max(1, height - 1) * 2.0 - 1.0)
        self.temperature = np.clip(
            0.12 + heat * 0.78 - np.clip(self.elevation - 0.50, 0.0, None) * 0.90, 0.0, 1.0
        ).astype(np.float32)

        # ---- 空白：没有水汽，没有草木，没有走兽 ----
        self.moisture = np.zeros((height, width), np.float32)
        self.soil = self._initial_soil()
        self.plants = np.zeros((height, width), np.float32)
        self.animals = np.zeros((height, width), np.float32)
        self.farms = np.zeros((height, width), np.float32)
        self._refresh_water()

    # ------------------------------------------------------------------ 基础
    def _carve_lakes(self, rng, yy, xx) -> None:
        """在大陆低洼处挖出几片湖泊，让生命一开始就有水可依。

        湖心优先选内陆偏低的地方，并按当地高度自动挖够深，
        这样哪怕整块大陆地势高耸，也仍会蓄下几汪水。
        """
        inner = np.zeros_like(self.elevation, bool)
        inner[8:self.h - 8, 8:self.w - 8] = True
        land = self.land_mask & inner
        if not land.any():
            return

        target = 4 + int(rng.integers(0, 3))
        coords = np.argwhere(land)              # (y, x)
        order = np.argsort(self.elevation[land])
        # 只在最低的那一半陆地里挑湖心，避免把湖挖到山尖上
        pool = coords[order[: max(1, int(len(order) * 0.5))]].astype(int)
        rng.shuffle(pool)

        # 第一片湖一定落在大陆重心附近，保证内陆宜居之地有活水
        ccy, ccx = coords.mean(axis=0)
        d2 = (coords[:, 0] - ccy) ** 2 + (coords[:, 1] - ccx) ** 2
        central = coords[int(np.argmin(d2))]
        pool = np.vstack([[central], pool])

        made, used = 0, []
        for cy, cx in pool:
            if made >= target:
                break
            if any((cx - ux) ** 2 + (cy - uy) ** 2 < 15 ** 2 for ux, uy in used):
                continue
            r = float(rng.integers(4, 9))
            dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
            f = np.clip(1.0 - dist / r, 0.0, 1.0).astype(np.float32)
            # 挖到水面之下为止，再略深一点
            need = max(0.0, self.elevation[cy, cx] - (self.sea_level - 0.03))
            depth = need + 0.04
            self.elevation = np.clip(self.elevation - depth * f, 0.0, 1.0).astype(np.float32)
            if self.elevation[cy, cx] <= self.sea_level:
                made += 1
                used.append((cx, cy))

    def _initial_soil(self) -> np.ndarray:
        land = self.land_mask
        # 低平的河谷最肥沃，高山贫瘠
        s = np.clip(1.25 - np.abs(self.elevation - 0.52) * 2.6, 0.05, 1.0)
        return (s * land * 0.75 + land * 0.15).astype(np.float32)

    @property
    def land_mask(self) -> np.ndarray:
        return self.elevation > self.sea_level

    @property
    def water_mask(self) -> np.ndarray:
        return ~self.land_mask

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def is_walkable(self, x: float, y: float) -> bool:
        xi, yi = int(x), int(y)
        if not self.in_bounds(xi, yi):
            return False
        return bool(self.elevation[yi, xi] > self.sea_level + 0.004)

    def _refresh_water(self) -> None:
        """重建水面判定缓存（边界补 True：界外一律视作水）。

        elevation 只会在造世与 reshape（画刷）中变化，两处都紧跟一次刷新。
        """
        self.water_pad = np.pad(self.elevation <= self.sea_level, 1, constant_values=True)

    def is_water(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return True
        return bool(self.water_pad[y + 1, x + 1])

    def clamp(self, x: float, y: float) -> tuple[float, float]:
        maxx = self.w - 1.001
        maxy = self.h - 1.001
        cx = x if 0.0 <= x <= maxx else (0.0 if x < 0.0 else maxx)
        cy = y if 0.0 <= y <= maxy else (0.0 if y < 0.0 else maxy)
        return cx, cy

    # ------------------------------------------------------------ 神的权柄
    def brush_slice(self, cx: int, cy: int, radius: int):
        x0, x1 = max(0, cx - radius), min(self.w, cx + radius + 1)
        y0, y1 = max(0, cy - radius), min(self.h, cy + radius + 1)
        return y0, y1, x0, x1

    def brush_falloff(self, cx: int, cy: int, radius: int) -> np.ndarray:
        """中心为 1、边缘为 0 的柔和笔刷。"""
        y0, y1, x0, x1 = self.brush_slice(cx, cy, radius)
        if y0 >= y1 or x0 >= x1:
            return np.zeros((0, 0), np.float32)
        gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        dist = np.sqrt((gx - cx) ** 2 + (gy - cy) ** 2)
        r = max(1.0, float(radius))
        return np.clip(1.0 - dist / r, 0.0, 1.0).astype(np.float32)

    def reshape(self, cx: int, cy: int, radius: int, delta: float) -> None:
        f = self.brush_falloff(cx, cy, radius)
        if f.size == 0:
            return
        y0, y1, x0, x1 = self.brush_slice(cx, cy, radius)
        old = self.elevation[y0:y1, x0:x1].copy()
        self.elevation[y0:y1, x0:x1] = np.clip(old + delta * f, 0.0, 1.0)
        # 地形一变，局部气温随之改变
        self.temperature[y0:y1, x0:x1] = np.clip(
            self.temperature[y0:y1, x0:x1] - delta * f * 0.9, 0.0, 1.0
        )
        if delta > 0:
            self.plants[y0:y1, x0:x1] *= (1.0 - f)
            self.animals[y0:y1, x0:x1] *= (1.0 - f)
        self._refresh_water()

    def add_moisture(self, cx: int, cy: int, radius: int, delta: float) -> None:
        f = self.brush_falloff(cx, cy, radius)
        if f.size == 0:
            return
        y0, y1, x0, x1 = self.brush_slice(cx, cy, radius)
        self.moisture[y0:y1, x0:x1] = np.clip(self.moisture[y0:y1, x0:x1] + delta * f, 0.0, 1.0)

    def add_temperature(self, cx: int, cy: int, radius: int, delta: float) -> None:
        f = self.brush_falloff(cx, cy, radius)
        if f.size == 0:
            return
        y0, y1, x0, x1 = self.brush_slice(cx, cy, radius)
        self.temperature[y0:y1, x0:x1] = np.clip(
            self.temperature[y0:y1, x0:x1] + delta * f, 0.0, 1.0
        )

    def add_soil(self, cx: int, cy: int, radius: int, delta: float) -> None:
        f = self.brush_falloff(cx, cy, radius)
        if f.size == 0:
            return
        y0, y1, x0, x1 = self.brush_slice(cx, cy, radius)
        self.soil[y0:y1, x0:x1] = np.clip(self.soil[y0:y1, x0:x1] + delta * f, 0.0, 1.0)

    def add_plants(self, cx: int, cy: int, radius: int, delta: float) -> None:
        f = self.brush_falloff(cx, cy, radius)
        if f.size == 0:
            return
        y0, y1, x0, x1 = self.brush_slice(cx, cy, radius)
        land = self.land_mask[y0:y1, x0:x1]
        self.plants[y0:y1, x0:x1] = np.clip(
            self.plants[y0:y1, x0:x1] + delta * f * land, 0.0, 1.0
        )

    def add_animals(self, cx: int, cy: int, radius: int, delta: float) -> None:
        f = self.brush_falloff(cx, cy, radius)
        if f.size == 0:
            return
        y0, y1, x0, x1 = self.brush_slice(cx, cy, radius)
        land = self.land_mask[y0:y1, x0:x1]
        self.animals[y0:y1, x0:x1] = np.clip(
            self.animals[y0:y1, x0:x1] + delta * f * land, 0.0, 1.0
        )

    def blight(self, cx: int, cy: int, radius: int, strength: float = 0.35) -> None:
        f = self.brush_falloff(cx, cy, radius)
        if f.size == 0:
            return
        y0, y1, x0, x1 = self.brush_slice(cx, cy, radius)
        self.plants[y0:y1, x0:x1] *= (1.0 - strength * f)
        self.animals[y0:y1, x0:x1] *= (1.0 - strength * f)
        self.soil[y0:y1, x0:x1] = np.clip(self.soil[y0:y1, x0:x1] - strength * 0.4 * f, 0.0, 1.0)

    # ------------------------------------------------------------ 气候演化
    def evolve(self) -> None:
        """世界自己的节奏：水汽流转、草木生长、走兽繁衍。"""
        self._climate()
        self._grow()

    def _climate(self) -> None:
        m = self.moisture
        # 水汽扩散
        lap = (np.roll(m, 1, 0) + np.roll(m, -1, 0) +
               np.roll(m, 1, 1) + np.roll(m, -1, 1)) * 0.25 - m
        m = m + lap * 0.20
        # 海面与炽热大地的蒸发
        evap = (self.water_mask * 0.014 +
                self.land_mask * np.clip(self.temperature - 0.45, 0.0, 1.0) * 0.005) * (1.0 - m)
        m = m + evap
        # 高空西风，把水汽吹向东方
        m = m * 0.992 + 0.010 * np.roll(m, 1, axis=1)
        # 迎风坡降雨：越高的地方越留不住水汽
        m = m * (1.0 - 0.05 * self.land_mask * np.clip(self.elevation - self.sea_level, 0.0, 1.0))
        self.moisture = np.clip(m, 0.0, 1.0).astype(np.float32)

    def _grow(self) -> None:
        land = self.land_mask
        cap = np.clip(1.65 * self.temperature * self.moisture * self.soil, 0.0, 1.0) * land
        p = self.plants
        growth = 0.180 * cap * (1.0 - p / np.maximum(cap, 1e-4))
        p = np.where(cap > 1e-3, np.clip(p + growth, 0.0, 1.0), p * 0.97)
        # 农田保水保肥
        p = np.clip(p + self.farms * 0.01, 0.0, 1.0)
        self.plants = np.clip(p * land, 0.0, 1.0).astype(np.float32)

        acap = np.clip(self.plants * 0.7, 0.0, 1.0)
        a = self.animals
        ag = 0.055 * acap * (1.0 - a / np.maximum(acap, 1e-4))
        a = np.where(acap > 1e-3, np.clip(a + ag, 0.0, 1.0), a * 0.96)
        self.animals = np.clip(a, 0.0, 1.0).astype(np.float32)

        # 根系的滋养生出土壤
        self.soil = np.clip(self.soil + 0.0022 * self.plants * land, 0.0, 1.0).astype(np.float32)
        self.farms = np.clip(self.farms * 0.999, 0.0, 1.0).astype(np.float32)

    # ------------------------------------------------------------ 世界读数
    def tile_info(self, x: int, y: int) -> dict:
        if not self.in_bounds(x, y):
            return {}
        return {
            "坐标": (x, y),
            "海拔": float(self.elevation[y, x]),
            "温度": float(self.temperature[y, x]),
            "水汽": float(self.moisture[y, x]),
            "土壤": float(self.soil[y, x]),
            "植被": float(self.plants[y, x]),
            "走兽": float(self.animals[y, x]),
            "地貌": self.biome_name(x, y),
        }

    def biome_name(self, x: int, y: int) -> str:
        e, t, m, p = (self.elevation[y, x], self.temperature[y, x],
                      self.moisture[y, x], self.plants[y, x])
        if e <= self.sea_level:
            return "深海" if e < self.sea_level - 0.14 else "浅海"
        if t < 0.26:
            return "雪原"
        if e > 0.78:
            return "岩石山地"
        if p > 0.62:
            return "森林"
        if p > 0.28:
            return "草原"
        if m < 0.16:
            return "荒漠"
        if t > 0.72 and m < 0.3:
            return "酷热之地"
        return "荒野"

    def color_array(self) -> np.ndarray:
        """把世界画成一张 (h, w, 3) 的 RGB 位图。"""
        elev, t, mo, pl = self.elevation, self.temperature, self.moisture, self.plants

        depth = np.clip((self.sea_level - elev) / 0.30, 0.0, 1.0)[..., None]
        water = _mix(np.array([72, 142, 192], np.float32),
                     np.array([10, 30, 74], np.float32), depth)

        desert = np.array([201, 176, 121], np.float32)
        grass = np.array([118, 155, 88], np.float32)
        forest = np.array([62, 108, 66], np.float32)
        rock = np.array([133, 129, 121], np.float32)
        snow = np.array([238, 242, 248], np.float32)
        tundra = np.array([160, 168, 160], np.float32)

        m = np.clip(mo / 0.42, 0.0, 1.0)[..., None]
        col = _mix(desert, grass, m)
        pf = np.clip(pl * 1.35, 0.0, 1.0)[..., None]
        col = _mix(col, forest, pf)
        rf = np.clip((elev - 0.72) / 0.22, 0.0, 1.0)[..., None]
        col = _mix(col, rock, rf)
        cf = np.clip((0.30 - t) / 0.28, 0.0, 1.0)[..., None]
        col = _mix(col, snow, cf)
        tf = (np.clip((0.46 - t) / 0.16, 0.0, 1.0)[..., None] *
              np.clip(1.0 - pl * 2.2, 0.0, 1.0)[..., None])
        col = _mix(col, tundra, tf)
        # 被反复耕作的土地留下浅金色的痕迹
        ff = (np.clip(self.farms, 0.0, 1.0) * 0.45)[..., None]
        col = _mix(col, np.array([216, 192, 104], np.float32), ff)

        out = np.where(self.water_mask[..., None], water, col)
        return np.clip(out, 0, 255).astype(np.uint8)

    def snapshot(self) -> dict:
        return {
            "elevation": self.elevation.copy(),
            "temperature": self.temperature.copy(),
            "moisture": self.moisture.copy(),
            "soil": self.soil.copy(),
            "plants": self.plants.copy(),
            "animals": self.animals.copy(),
        }

    def restore(self, data: dict) -> None:
        for key, value in data.items():
            setattr(self, key, value.copy())