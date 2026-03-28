"""
ML-optimized stage analyzer.

Ports the HTML ML-Optimized analyzer logic to Python.
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen

from src.data.kml_parser import Coordinate, KMLData

logger = logging.getLogger(__name__)


@dataclass
class MLOptimizedResult:
    name: str
    distance_km: float
    curvature_sum: float
    curvature_density: float
    p95_curvature: float
    max_curvature: float
    straight_ratio: float
    hairpin_density: float
    hairpin_count: int
    sign_changes_per_km: float
    total_ascent: float
    total_descent: float
    max_grade: float
    avg_abs_grade: float
    geometry_points: int
    elevation_api_calls: int
    cache_hit_rate: float


class MLOptimizedAnalyzer:
    """
    Analyze stage geometry with ML-optimized features.

    This mirrors the logic in etap_ml_v1.html:
    - Fixed 10m geometry sampling (default)
    - UTM conversion (zone 36N)
    - Moving-average smoothing
    - Curvature via heading deltas
    - Sparse elevation sampling via Open-Meteo API
    """

    def __init__(
        self,
        geom_step_m: int = 10,
        elev_step_m: int = 200,
        smooth_window: int = 7,
        hairpin_threshold_m: float = 20.0,
        elevation_cache_path: Optional[Path] = None,
        use_elevation_api: bool = True,
    ):
        self.geom_step_m = geom_step_m
        self.elev_step_m = elev_step_m
        self.smooth_window = smooth_window if smooth_window % 2 == 1 else smooth_window + 1
        self.hairpin_threshold_m = hairpin_threshold_m
        self.use_elevation_api = use_elevation_api
        self._api_call_times: List[float] = []
        self._cache: Dict[str, float] = {}
        self._cache_path = elevation_cache_path
        if self._cache_path:
            self._load_cache()

    def analyze_kml_data(self, kml_data: KMLData) -> Optional[MLOptimizedResult]:
        coords = kml_data.coordinates
        if len(coords) < 2:
            logger.warning("Insufficient coordinates for ML analysis: %s", len(coords))
            return None

        samples = self._sample_line(coords, self.geom_step_m)
        if len(samples) < 3:
            logger.warning("Insufficient sampled points for ML analysis: %s", len(samples))
            return None

        utm_points = [self._latlon_to_utm(p.latitude, p.longitude) for p in samples]
        x_vals = [p[0] for p in utm_points]
        y_vals = [p[1] for p in utm_points]
        x_smooth = self._moving_average(x_vals, self.smooth_window)
        y_smooth = self._moving_average(y_vals, self.smooth_window)

        smoothed = list(zip(x_smooth, y_smooth))

        curvatures, signed_curvatures = self._calculate_curvature(smoothed)
        radii = self._calculate_radii(smoothed)

        elevations, api_calls, cache_hit_rate = self._get_elevations(samples)
        grades, total_ascent, total_descent = self._calculate_grades(elevations)

        distance_km = (len(samples) - 1) * self.geom_step_m / 1000.0
        distance_km = max(distance_km, 0.001)

        curvature_sum = sum(abs(c) * self.geom_step_m for c in signed_curvatures)
        curvature_density = curvature_sum / distance_km

        curvature_values = sorted(curvatures)
        p95_index = int(len(curvature_values) * 0.95)
        p95_curvature = curvature_values[p95_index] if curvature_values else 0.0
        max_curvature = max(curvature_values) if curvature_values else 0.0

        straight_count = sum(1 for c in curvatures if c < 0.005)
        straight_ratio = straight_count / max(len(curvatures), 1)

        hairpin_count = sum(1 for r in radii if r < self.hairpin_threshold_m)
        hairpin_density = hairpin_count / distance_km

        sign_changes = 0
        for i in range(1, len(signed_curvatures)):
            if math.copysign(1, signed_curvatures[i]) != math.copysign(1, signed_curvatures[i - 1]):
                sign_changes += 1
        sign_changes_per_km = sign_changes / distance_km

        max_grade = max([abs(g) for g in grades]) if grades else 0.0
        avg_abs_grade = sum(abs(g) for g in grades) / max(len(grades), 1)

        return MLOptimizedResult(
            name=kml_data.name,
            distance_km=distance_km,
            curvature_sum=curvature_sum,
            curvature_density=curvature_density,
            p95_curvature=p95_curvature,
            max_curvature=max_curvature,
            straight_ratio=straight_ratio,
            hairpin_density=hairpin_density,
            hairpin_count=hairpin_count,
            sign_changes_per_km=sign_changes_per_km,
            total_ascent=total_ascent,
            total_descent=total_descent,
            max_grade=max_grade,
            avg_abs_grade=avg_abs_grade,
            geometry_points=len(samples),
            elevation_api_calls=api_calls,
            cache_hit_rate=cache_hit_rate,
        )

    def _sample_line(self, coords: List[Coordinate], step_m: int) -> List[Coordinate]:
        distances = [0.0]
        for i in range(1, len(coords)):
            d = self._haversine_m(coords[i - 1], coords[i])
            distances.append(distances[-1] + d)

        total = distances[-1]
        if total <= 0:
            return coords[:]

        sampled: List[Coordinate] = []
        target = 0.0
        idx = 1
        while target <= total and idx < len(coords):
            while idx < len(coords) and distances[idx] < target:
                idx += 1
            if idx >= len(coords):
                break
            prev = coords[idx - 1]
            curr = coords[idx]
            d0 = distances[idx - 1]
            d1 = distances[idx]
            ratio = 0.0 if d1 == d0 else (target - d0) / (d1 - d0)
            lat = prev.latitude + (curr.latitude - prev.latitude) * ratio
            lon = prev.longitude + (curr.longitude - prev.longitude) * ratio
            sampled.append(Coordinate(latitude=lat, longitude=lon))
            target += step_m

        if sampled and (sampled[-1].latitude != coords[-1].latitude or sampled[-1].longitude != coords[-1].longitude):
            sampled.append(Coordinate(latitude=coords[-1].latitude, longitude=coords[-1].longitude))
        return sampled

    def _moving_average(self, values: List[float], window: int) -> List[float]:
        if window <= 1:
            return values[:]
        half = window // 2
        smoothed = []
        for i in range(len(values)):
            start = max(0, i - half)
            end = min(len(values), i + half + 1)
            segment = values[start:end]
            smoothed.append(sum(segment) / len(segment))
        return smoothed

    def _calculate_curvature(self, points: List[Tuple[float, float]]) -> Tuple[List[float], List[float]]:
        headings = []
        for i in range(len(points) - 1):
            dx = points[i + 1][0] - points[i][0]
            dy = points[i + 1][1] - points[i][1]
            headings.append(math.atan2(dy, dx))

        curvatures = []
        signed = []
        for i in range(1, len(headings)):
            dh = headings[i] - headings[i - 1]
            while dh > math.pi:
                dh -= 2 * math.pi
            while dh < -math.pi:
                dh += 2 * math.pi
            curvature = abs(dh) / self.geom_step_m
            curvatures.append(curvature)
            signed.append(dh / self.geom_step_m)
        return curvatures, signed

    def _calculate_radii(self, points: List[Tuple[float, float]]) -> List[float]:
        radii = []
        for i in range(1, len(points) - 1):
            ax, ay = points[i - 1]
            bx, by = points[i]
            cx, cy = points[i + 1]

            a = math.hypot(bx - cx, by - cy)
            b = math.hypot(ax - cx, ay - cy)
            c = math.hypot(ax - bx, ay - by)
            s = (a + b + c) / 2
            area = math.sqrt(max(0.0, s * (s - a) * (s - b) * (s - c)))
            r = (a * b * c) / (4 * area) if area > 1e-9 else float('inf')
            radii.append(r)
        return radii

    def _get_elevations(self, samples: List[Coordinate]) -> Tuple[List[float], int, float]:
        if not self.use_elevation_api:
            return [0.0 for _ in samples], 0, 0.0

        elev_indices = list(range(0, len(samples), max(1, self.elev_step_m // self.geom_step_m)))
        if elev_indices[-1] != len(samples) - 1:
            elev_indices.append(len(samples) - 1)

        batch_size = 100
        sparse_elev = []
        total_uncached = 0
        api_calls = 0

        try:
            for i in range(0, len(elev_indices), batch_size):
                batch_idx = elev_indices[i:i + batch_size]
                coords = [(samples[idx].latitude, samples[idx].longitude) for idx in batch_idx]
                cached = [None] * len(coords)
                uncached_coords = []
                uncached_positions = []

                for j, (lat, lon) in enumerate(coords):
                    key = self._cache_key(lat, lon)
                    if key in self._cache:
                        cached[j] = self._cache[key]
                    else:
                        uncached_coords.append((lat, lon))
                        uncached_positions.append(j)

                if uncached_coords:
                    total_uncached += len(uncached_coords)
                    api_calls += 1
                    elevations = self._fetch_elevation_batch(uncached_coords)
                    for pos, elev, (lat, lon) in zip(uncached_positions, elevations, uncached_coords):
                        cached[pos] = elev
                        self._cache[self._cache_key(lat, lon)] = elev
                    if self._cache_path:
                        self._save_cache()
                sparse_elev.extend(cached)
        except Exception as exc:
            logger.warning("Elevation fetch failed, falling back to zeros: %s", exc)
            return [0.0 for _ in samples], api_calls, 0.0

        elevations = self._linear_interpolate(elev_indices, sparse_elev, len(samples))
        cache_hit_rate = 0.0
        if elev_indices:
            cache_hit_rate = max(0.0, 1.0 - (total_uncached / len(elev_indices)))
        return elevations, api_calls, cache_hit_rate

    def _calculate_grades(self, elevations: List[float]) -> Tuple[List[float], float, float]:
        grades = [0.0]
        total_ascent = 0.0
        total_descent = 0.0

        for i in range(1, len(elevations)):
            elev_diff = elevations[i] - elevations[i - 1]
            grade = (elev_diff / self.geom_step_m) * 100
            grades.append(grade)
            if elev_diff > 0:
                total_ascent += elev_diff
            else:
                total_descent += abs(elev_diff)

        return grades, total_ascent, total_descent

    def _linear_interpolate(self, indices: List[int], values: List[float], target_len: int) -> List[float]:
        result = [0.0] * target_len
        for i in range(target_len):
            left = 0
            right = len(indices) - 1
            for j in range(len(indices) - 1):
                if indices[j] <= i <= indices[j + 1]:
                    left = j
                    right = j + 1
                    break
            x1 = indices[left]
            x2 = indices[right]
            y1 = values[left]
            y2 = values[right]
            if x2 == x1:
                result[i] = y1
            else:
                t = (i - x1) / (x2 - x1)
                result[i] = y1 + t * (y2 - y1)
        return result

    def _fetch_elevation_batch(self, coords: List[Tuple[float, float]]) -> List[float]:
        lats = ",".join(f"{lat:.6f}" for lat, _ in coords)
        lons = ",".join(f"{lon:.6f}" for _, lon in coords)
        url = f"https://api.open-meteo.com/v1/elevation?latitude={lats}&longitude={lons}"

        self._rate_limit()

        with urlopen(url) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elevations = data.get("elevation", [])
        if len(elevations) != len(coords):
            logger.warning("Elevation API returned %s points for %s coords", len(elevations), len(coords))
            elevations = elevations[:len(coords)] + [0.0] * max(0, len(coords) - len(elevations))
        return elevations

    def _rate_limit(self):
        now = time.time()
        self._api_call_times = [t for t in self._api_call_times if now - t < 60]
        if len(self._api_call_times) >= 50:
            wait_time = 61 - (now - self._api_call_times[0])
            if wait_time > 0:
                time.sleep(wait_time)
            self._api_call_times = []
        self._api_call_times.append(time.time())

    def _cache_key(self, lat: float, lon: float) -> str:
        return f"{lat:.6f},{lon:.6f}"

    def _load_cache(self):
        if not self._cache_path or not self._cache_path.exists():
            return
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
        except Exception as exc:
            logger.warning("Failed to load elevation cache: %s", exc)
            self._cache = {}

    def _save_cache(self):
        if not self._cache_path:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f)
        except Exception as exc:
            logger.warning("Failed to save elevation cache: %s", exc)

    def _latlon_to_utm(self, lat: float, lon: float) -> Tuple[float, float]:
        zone = 36
        lon0 = (zone - 1) * 6 - 180 + 3

        a = 6378137.0
        e = 0.081819191
        k0 = 0.9996

        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        lon0_rad = math.radians(lon0)

        n = a / math.sqrt(1 - e * e * math.sin(lat_rad) ** 2)
        t = math.tan(lat_rad) ** 2
        c = (e * e / (1 - e * e)) * math.cos(lat_rad) ** 2
        A = (lon_rad - lon0_rad) * math.cos(lat_rad)

        m = a * (
            (1 - e * e / 4 - 3 * e ** 4 / 64) * lat_rad
            - (3 * e * e / 8 + 3 * e ** 4 / 32) * math.sin(2 * lat_rad)
            + (15 * e ** 4 / 256) * math.sin(4 * lat_rad)
        )

        x = k0 * n * (
            A
            + (1 - t + c) * A ** 3 / 6
            + (5 - 18 * t + t * t + 72 * c) * A ** 5 / 120
        )
        y = k0 * (m + n * math.tan(lat_rad) * (A * A / 2 + (5 - t + 9 * c + 4 * c * c) * A ** 4 / 24))

        return x + 500000, y

    def _haversine_m(self, a: Coordinate, b: Coordinate) -> float:
        r = 6371000.0
        lat1 = math.radians(a.latitude)
        lat2 = math.radians(b.latitude)
        dlat = lat2 - lat1
        dlon = math.radians(b.longitude - a.longitude)
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 2 * r * math.atan2(math.sqrt(h), math.sqrt(1 - h))
