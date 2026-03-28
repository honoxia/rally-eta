"""
RallyETA v2 - KML Stage Analyzer
Analyzes KML/KMZ files to extract geometric stage features using ML-optimized approach.

This module implements the same algorithms as etap_ml_v1.html but in Python:
- UTM Zone 36N projection for meter-based geometry
- 10m geometry sampling (no API)
- 200m elevation sampling with cubic interpolation
- Savitzky-Golay GPS noise filtering
- Curvature-based features (κ = |Δθ/Δs|)
"""

import numpy as np
from typing import List, Tuple, Dict
import xml.etree.ElementTree as ET
from pathlib import Path
import zipfile
from scipy.interpolate import CubicSpline
from scipy.signal import savgol_filter
import math
import requests
import time
import re


class KMLAnalyzer:
    """Analyzes KML/KMZ stage files to extract geometric features."""

    def __init__(self, geom_step: float = 10.0, smoothing_window: int = 7, elev_step: float = 200.0):
        """
        Initialize the KML analyzer.

        Args:
            geom_step: Geometry sampling interval in meters (default: 10m)
            smoothing_window: Savitzky-Golay smoothing window size (default: 7)
            elev_step: Elevation sampling interval in meters (default: 200m for API efficiency)
        """
        self.geom_step = geom_step
        self.smoothing_window = smoothing_window
        self.elev_step = elev_step
        self.utm_zone = 36  # Turkey: Zone 36N
        self.elevation_cache = {}  # Cache for API calls

    def analyze_kml(self, kml_path: str, hairpin_threshold: float = 20.0) -> Dict:
        """
        Analyze a KML/KMZ file and extract all geometric features.

        Args:
            kml_path: Path to KML or KMZ file
            hairpin_threshold: Radius threshold for hairpin detection in meters (default: 20m)

        Returns:
            Dictionary with all stage features
        """
        # Parse KML
        coordinates = self._parse_kml(kml_path)

        if len(coordinates) < 2:
            raise ValueError(f"KML file has insufficient coordinates: {len(coordinates)}")

        # Convert to UTM
        utm_points = [self._lat_lon_to_utm(lat, lon) for lat, lon in coordinates]

        # Resample to uniform geometry step (10m)
        resampled = self._resample_path(utm_points, self.geom_step)

        # Also create resampled lat/lon coordinates for elevation
        # Use Turf-like along() by calculating distance-based sampling
        resampled_coords = self._resample_coordinates(coordinates, self.geom_step)

        # Apply Savitzky-Golay smoothing
        smoothed = self._smooth_path(resampled)

        # Calculate curvature (2D geometry only)
        curvatures = self._calculate_curvature(smoothed)

        # Extract features
        features = self._extract_features(smoothed, curvatures, resampled_coords, hairpin_threshold)

        features['kml_file_path'] = kml_path
        features['geometry_samples'] = len(smoothed)

        return features

    def _parse_xml_with_encoding(self, source):
        """
        Parse XML with multiple encoding attempts to handle problematic files.

        Args:
            source: File path or file-like object

        Returns:
            ElementTree object
        """
        encodings = ['utf-8', 'utf-8-sig', 'iso-8859-1', 'windows-1252', 'latin1']

        # If it's a file path, read and try different encodings
        if isinstance(source, (str, Path)):
            for encoding in encodings:
                try:
                    with open(source, 'r', encoding=encoding) as f:
                        content = f.read()
                    # Parse from string
                    return ET.ElementTree(ET.fromstring(content))
                except (UnicodeDecodeError, ET.ParseError) as e:
                    if encoding == encodings[-1]:
                        # Last attempt failed, try to clean the file
                        try:
                            with open(source, 'rb') as f:
                                raw_content = f.read()
                            # Decode with error handling
                            content = raw_content.decode('utf-8', errors='replace')
                            # Remove invalid XML characters
                            # Remove control characters except tab, newline, carriage return
                            content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', content)
                            return ET.ElementTree(ET.fromstring(content))
                        except Exception as final_error:
                            raise ValueError(f"Failed to parse KML file. Last error: {final_error}")
                    continue
        else:
            # It's a file-like object (from KMZ)
            try:
                content = source.read()
                if isinstance(content, bytes):
                    # Try to decode with different encodings
                    for encoding in encodings:
                        try:
                            text_content = content.decode(encoding)
                            return ET.ElementTree(ET.fromstring(text_content))
                        except (UnicodeDecodeError, ET.ParseError):
                            if encoding == encodings[-1]:
                                # Clean and try again
                                text_content = content.decode('utf-8', errors='replace')
                                text_content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text_content)
                                return ET.ElementTree(ET.fromstring(text_content))
                            continue
                else:
                    return ET.parse(source)
            except Exception as e:
                raise ValueError(f"Failed to parse KML from archive: {e}")

    def _parse_kml(self, kml_path: str) -> List[Tuple[float, float]]:
        """
        Parse KML/KMZ file and extract coordinates.

        Args:
            kml_path: Path to KML or KMZ file

        Returns:
            List of (lat, lon) tuples
        """
        kml_path = Path(kml_path)

        # Handle KMZ (zipped KML)
        if kml_path.suffix.lower() == '.kmz':
            with zipfile.ZipFile(kml_path, 'r') as kmz:
                # Find first .kml file in archive
                kml_files = [f for f in kmz.namelist() if f.endswith('.kml')]
                if not kml_files:
                    raise ValueError(f"No KML file found in KMZ: {kml_path}")
                with kmz.open(kml_files[0]) as kml_file:
                    tree = self._parse_xml_with_encoding(kml_file)
        else:
            tree = self._parse_xml_with_encoding(kml_path)

        root = tree.getroot()

        # Handle KML namespace
        namespace = {'kml': 'http://www.opengis.net/kml/2.2'}
        if root.tag.startswith('{'):
            # Extract namespace from root tag
            namespace_uri = root.tag.split('}')[0].strip('{')
            namespace = {'kml': namespace_uri}

        # Find coordinates in LineString or Path
        coordinates_elements = root.findall('.//kml:coordinates', namespace)
        if not coordinates_elements:
            # Try without namespace
            coordinates_elements = root.findall('.//coordinates')

        if not coordinates_elements:
            raise ValueError(f"No coordinates found in KML file: {kml_path}")

        # Parse coordinates (format: "lon,lat,alt lon,lat,alt ...")
        coordinates = []
        for elem in coordinates_elements:
            coord_text = elem.text.strip()
            for coord in coord_text.split():
                parts = coord.split(',')
                if len(parts) >= 2:
                    lon, lat = float(parts[0]), float(parts[1])
                    coordinates.append((lat, lon))

        return coordinates

    def _lat_lon_to_utm(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        Convert WGS84 lat/lon to UTM Zone 36N coordinates.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees

        Returns:
            (easting, northing) in meters
        """
        # WGS84 parameters
        a = 6378137.0  # Semi-major axis
        e = 0.081819191  # Eccentricity
        k0 = 0.9996  # Scale factor

        # Convert to radians
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)

        # Central meridian for Zone 36
        lon0 = math.radians((self.utm_zone - 1) * 6 - 180 + 3)

        # Calculations
        N = a / math.sqrt(1 - e * e * math.sin(lat_rad) ** 2)
        T = math.tan(lat_rad) ** 2
        C = (e * e / (1 - e * e)) * math.cos(lat_rad) ** 2
        A = (lon_rad - lon0) * math.cos(lat_rad)

        M = a * (
            (1 - e * e / 4 - 3 * e ** 4 / 64 - 5 * e ** 6 / 256) * lat_rad
            - (3 * e * e / 8 + 3 * e ** 4 / 32 + 45 * e ** 6 / 1024) * math.sin(2 * lat_rad)
            + (15 * e ** 4 / 256 + 45 * e ** 6 / 1024) * math.sin(4 * lat_rad)
            - (35 * e ** 6 / 3072) * math.sin(6 * lat_rad)
        )

        easting = k0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T ** 2 + 72 * C - 58 * (e * e / (1 - e * e))) * A ** 5 / 120) + 500000
        northing = k0 * (M + N * math.tan(lat_rad) * (A ** 2 / 2 + (5 - T + 9 * C + 4 * C ** 2) * A ** 4 / 24 + (61 - 58 * T + T ** 2 + 600 * C - 330 * (e * e / (1 - e * e))) * A ** 6 / 720))

        return (easting, northing)

    def _resample_path(self, points: List[Tuple[float, float]], step: float) -> List[Tuple[float, float]]:
        """
        Resample path to uniform step size.

        Args:
            points: List of (easting, northing) UTM points
            step: Target step size in meters

        Returns:
            Resampled points with uniform spacing
        """
        if len(points) < 2:
            return points

        # Calculate cumulative distance
        distances = [0.0]
        for i in range(1, len(points)):
            dx = points[i][0] - points[i-1][0]
            dy = points[i][1] - points[i-1][1]
            dist = math.sqrt(dx*dx + dy*dy)
            distances.append(distances[-1] + dist)

        total_distance = distances[-1]

        # Create interpolation functions
        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]

        # Linear interpolation for resampling
        resampled = []
        current_dist = 0.0

        while current_dist <= total_distance:
            # Find segment
            idx = 0
            for i in range(len(distances) - 1):
                if distances[i] <= current_dist <= distances[i+1]:
                    idx = i
                    break

            # Linear interpolation
            if idx < len(distances) - 1:
                segment_dist = distances[idx+1] - distances[idx]
                if segment_dist > 0:
                    t = (current_dist - distances[idx]) / segment_dist
                else:
                    t = 0
                x = x_coords[idx] + t * (x_coords[idx+1] - x_coords[idx])
                y = y_coords[idx] + t * (y_coords[idx+1] - y_coords[idx])
                resampled.append((x, y))

            current_dist += step

        # Ensure at least 2 points
        if len(resampled) < 2 and len(points) >= 2:
            return points[:2]

        return resampled

    def _resample_coordinates(self, coords: List[Tuple[float, float]], step: float) -> List[Tuple[float, float]]:
        """
        Resample lat/lon coordinates at uniform distance intervals (like turf.along()).

        Args:
            coords: List of (lat, lon) tuples
            step: Target step size in meters

        Returns:
            Resampled coordinates with uniform spacing
        """
        if len(coords) < 2:
            return coords

        # Calculate cumulative distance using Haversine
        from math import radians, sin, cos, sqrt, atan2

        def haversine(lat1, lon1, lat2, lon2):
            R = 6371000  # Earth radius in meters
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
            c = 2 * atan2(sqrt(a), sqrt(1-a))
            return R * c

        distances = [0.0]
        for i in range(1, len(coords)):
            dist = haversine(coords[i-1][0], coords[i-1][1], coords[i][0], coords[i][1])
            distances.append(distances[-1] + dist)

        total_distance = distances[-1]

        # Resample
        resampled = []
        current_dist = 0.0

        while current_dist <= total_distance:
            # Find segment
            idx = 0
            for i in range(len(distances) - 1):
                if distances[i] <= current_dist <= distances[i+1]:
                    idx = i
                    break

            # Linear interpolation
            if idx < len(distances) - 1:
                segment_dist = distances[idx+1] - distances[idx]
                if segment_dist > 0:
                    t = (current_dist - distances[idx]) / segment_dist
                else:
                    t = 0
                lat = coords[idx][0] + t * (coords[idx+1][0] - coords[idx][0])
                lon = coords[idx][1] + t * (coords[idx+1][1] - coords[idx][1])
                resampled.append((lat, lon))

            current_dist += step

        # Ensure at least 2 points
        if len(resampled) < 2 and len(coords) >= 2:
            return coords[:2]

        return resampled

    def _smooth_path(self, points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """
        Apply smoothing to remove GPS noise - MATCHING HTML ALGORITHM (lines 164-178).

        HTML uses simplified "Savitzky-Golay" which is actually just moving average.
        This matches HTML behavior exactly for consistency.

        Args:
            points: List of (easting, northing) points

        Returns:
            Smoothed points
        """
        if len(points) < self.smoothing_window:
            return points

        x_coords = np.array([p[0] for p in points])
        y_coords = np.array([p[1] for p in points])

        # HTML's "simplified SG filter" (line 164) - actually moving average
        half_window = self.smoothing_window // 2
        x_smooth = np.zeros(len(x_coords))
        y_smooth = np.zeros(len(y_coords))

        for i in range(len(points)):
            start = max(0, i - half_window)
            end = min(len(points), i + half_window + 1)
            x_smooth[i] = np.mean(x_coords[start:end])
            y_smooth[i] = np.mean(y_coords[start:end])

        return list(zip(x_smooth, y_smooth))

    def _calculate_curvature(self, points: List[Tuple[float, float]]) -> List[float]:
        """
        Calculate curvature at each point (κ = |Δθ/Δs|).

        Args:
            points: List of (easting, northing) points

        Returns:
            List of curvature values in 1/m
        """
        if len(points) < 3:
            return [0.0] * len(points)

        curvatures = [0.0]  # First point

        for i in range(1, len(points) - 1):
            # Vectors to previous and next points
            dx1 = points[i][0] - points[i-1][0]
            dy1 = points[i][1] - points[i-1][1]
            dx2 = points[i+1][0] - points[i][0]
            dy2 = points[i+1][1] - points[i][1]

            # Headings
            h1 = math.atan2(dy1, dx1)
            h2 = math.atan2(dy2, dx2)

            # Change in heading (handle wraparound)
            dh = h2 - h1
            if dh > math.pi:
                dh -= 2 * math.pi
            elif dh < -math.pi:
                dh += 2 * math.pi

            # Segment distance
            segment_dist = self.geom_step

            # Curvature (1/m)
            curvature = abs(dh) / segment_dist if segment_dist > 0 else 0.0
            curvatures.append(curvature)

        curvatures.append(0.0)  # Last point

        return curvatures

    def _extract_features(self, points: List[Tuple[float, float]],
                         curvatures: List[float],
                         original_coords: List[Tuple[float, float]],
                         hairpin_threshold: float = 20.0) -> Dict:
        """
        Extract all geometric features from analyzed path.

        Args:
            points: Smoothed UTM points
            curvatures: Curvature values
            original_coords: Original lat/lon coordinates for elevation
            hairpin_threshold: Radius threshold for hairpin detection in meters (default: 20m)

        Returns:
            Dictionary with all features
        """
        # Distance
        total_distance = max(len(points) * self.geom_step / 1000.0, 0.001)  # km, min 1m to avoid div by 0

        # Curvature features
        curvature_array = np.array(curvatures) if len(curvatures) > 0 else np.array([0.0])

        # CRITICAL FIX: Calculate signed curvature FIRST
        signed_curvatures = self._calculate_signed_curvature(points)
        if len(signed_curvatures) == 0:
            signed_curvatures = np.array([0.0])

        # CRITICAL FIX: curvature_sum must be in radians (sum of |signed_curvature| * distance)
        # signed_curvatures now returns N-2 elements (matching HTML exactly)
        # This matches the HTML algorithm (line 654): curvatureSum = Σ(|signed_curvature| * geomStep)
        curvature_sum = float(np.sum(np.abs(signed_curvatures)) * self.geom_step)  # radians
        curvature_density = curvature_sum / total_distance if total_distance > 0 else 0.0
        avg_curvature = float(np.mean(curvature_array))
        p50_curvature = float(np.median(curvature_array))
        p95_curvature = float(np.percentile(curvature_array, 95))
        max_curvature = float(np.max(curvature_array))

        # Hairpin features - use 3-point radius method (matching HTML lines 526-541)
        radii = self._calculate_radii(points)
        radii_array = np.array(radii) if len(radii) > 0 else np.array([float('inf')])
        hairpin_mask = radii_array < hairpin_threshold
        hairpin_count = int(np.sum(hairpin_mask))
        hairpin_density = hairpin_count / total_distance if total_distance > 0 else 0.0

        # Avg hairpin curvature - ensure arrays have matching lengths
        if hairpin_count > 0 and len(curvature_array) == len(radii_array):
            avg_hairpin_curvature = float(np.mean(curvature_array[hairpin_mask]))
        else:
            avg_hairpin_curvature = 0.0

        # Straight sections (matching HTML line 661)
        straight_threshold = 0.005  # 1/m - very low curvature
        straight_count = int(np.sum(curvature_array < straight_threshold))
        straight_ratio = straight_count / len(curvature_array) if len(curvature_array) > 0 else 0.0

        # Sign changes (direction changes)
        sign_changes = int(np.sum(np.diff(np.sign(signed_curvatures)) != 0))
        sign_changes_per_km = sign_changes / total_distance if total_distance > 0 else 0.0

        # Average turn length
        avg_turn_length = (total_distance * 1000) / sign_changes if sign_changes > 0 else 0.0

        # Elevation features (fetch from API, matching HTML lines 544-619)
        print("[INFO] Fetching elevation data...")

        # Sample coordinates at elevation step interval
        # Now using properly resampled coordinates (original_coords is actually resampled_coords)
        num_geom_samples = len(points)
        elev_interval = int(self.elev_step / self.geom_step)
        elev_indices = list(range(0, num_geom_samples, elev_interval))

        # Ensure last point is included
        if elev_indices[-1] != num_geom_samples - 1:
            elev_indices.append(num_geom_samples - 1)

        # Get corresponding lat/lon coordinates from resampled_coords
        # Filter both indices and coords together to maintain alignment
        valid_pairs = [(idx, original_coords[idx]) for idx in elev_indices if idx < len(original_coords)]

        if not valid_pairs:
            # No elevation data available
            elevations = np.zeros(num_geom_samples)
        else:
            valid_indices = [p[0] for p in valid_pairs]
            sample_coords = [p[1] for p in valid_pairs]

            print(f"[API] Fetching {len(sample_coords)} elevation points...")

            # Fetch elevations
            sparse_elevations = self._fetch_elevations(sample_coords)

            # Interpolate to full resolution - MATCHING HTML (lines 198-209)
            # HTML uses LINEAR interpolation (not cubic!) to avoid spikes
            if len(sparse_elevations) > 1 and len(valid_indices) == len(sparse_elevations):
                from scipy.interpolate import interp1d
                # Use LINEAR interpolation like HTML (comment says "cubic" but code is linear)
                interp_func = interp1d(valid_indices, sparse_elevations, kind='linear', fill_value="extrapolate")
                elevations = interp_func(range(num_geom_samples))

                # HTML doesn't smooth elevation after interpolation
                # Linear interpolation is smooth enough, no additional smoothing needed
            elif len(sparse_elevations) > 0:
                # Fallback: use mean elevation
                elevations = np.full(num_geom_samples, np.mean(sparse_elevations))
            else:
                elevations = np.zeros(num_geom_samples)

        # Calculate elevation features
        grades = [0.0]  # First point
        total_ascent = 0.0
        total_descent = 0.0

        for i in range(1, len(elevations)):
            elev_diff = elevations[i] - elevations[i - 1]
            grade = (elev_diff / self.geom_step) * 100  # percentage
            grades.append(grade)

            if elev_diff > 0:
                total_ascent += elev_diff
            else:
                total_descent += abs(elev_diff)

        grades_array = np.array(grades)
        max_grade = float(np.max(np.abs(grades_array)))
        avg_abs_grade = float(np.mean(np.abs(grades_array)))

        elevation_features = {
            'total_ascent': float(total_ascent),
            'total_descent': float(total_descent),
            'max_grade': max_grade,
            'min_grade': float(np.min(grades_array)),
            'avg_abs_grade': avg_abs_grade,
            'p95_grade': float(np.percentile(np.abs(grades_array), 95)),
            'grade_std': float(np.std(grades_array)),
            'ascent_hairpin_count': 0,  # TODO: calculate hairpins on ascent vs descent
            'descent_hairpin_count': 0,
            'elevation_samples': len(sample_coords)
        }

        print(f"[OK] Elevation: +{total_ascent:.0f}m / -{total_descent:.0f}m, Max grade: {max_grade:.1f}%")

        return {
            'distance_km': total_distance,
            'curvature_sum': curvature_sum,
            'curvature_density': curvature_density,
            'p50_curvature': p50_curvature,
            'p95_curvature': p95_curvature,
            'max_curvature': max_curvature,
            'avg_curvature': avg_curvature,
            'hairpin_count': hairpin_count,
            'hairpin_density': hairpin_density,
            'avg_hairpin_curvature': avg_hairpin_curvature,
            'straight_ratio': straight_ratio,
            'sign_changes': sign_changes,
            'sign_changes_per_km': sign_changes_per_km,
            'avg_turn_length': avg_turn_length,
            **elevation_features
        }

    def _calculate_signed_curvature(self, points: List[Tuple[float, float]]) -> np.ndarray:
        """
        Calculate signed curvature - EXACT HTML ALGORITHM (lines 501-523).

        HTML Algorithm:
        1. Calculate headings between consecutive points (N-1 headings from N points)
        2. Calculate curvature from consecutive heading differences (N-2 curvatures)
        3. Use constant geomStep for all segments

        Args:
            points: List of (easting, northing) points

        Returns:
            Array of signed curvature values (N-2 elements)
        """
        if len(points) < 3:
            return np.zeros(0)

        # Step 1: Calculate headings between consecutive points (HTML lines 501-505)
        headings = []
        for i in range(len(points) - 1):
            dx = points[i+1][0] - points[i][0]
            dy = points[i+1][1] - points[i][1]
            headings.append(math.atan2(dy, dx))

        # Step 2: Calculate curvature from heading differences (HTML lines 507-523)
        signed_curvatures = []
        for i in range(1, len(headings)):
            dh = headings[i] - headings[i-1]

            # Wrap to [-π, π] (HTML lines 509-511)
            while dh > math.pi:
                dh -= 2 * math.pi
            while dh < -math.pi:
                dh += 2 * math.pi

            # HTML line 515: signedCurvature = dh / segmentDist
            # HTML uses constant geomStep (10m) for all segments
            curvature = dh / self.geom_step if self.geom_step > 0 else 0.0
            signed_curvatures.append(curvature)

        return np.array(signed_curvatures)

    def _calculate_radii(self, points: List[Tuple[float, float]]) -> List[float]:
        """
        Calculate turn radius using 3-point circle method (matching HTML lines 526-541).

        Args:
            points: List of (easting, northing) points

        Returns:
            List of radius values in meters
        """
        if len(points) < 3:
            return [float('inf')] * len(points)

        radii = [float('inf')]  # First point

        for i in range(1, len(points) - 1):
            A = points[i - 1]
            B = points[i]
            C = points[i + 1]

            # Triangle side lengths
            a = math.hypot(B[0] - C[0], B[1] - C[1])
            b = math.hypot(A[0] - C[0], A[1] - C[1])
            c = math.hypot(A[0] - B[0], A[1] - B[1])

            # Heron's formula for triangle area
            s = (a + b + c) / 2
            area = math.sqrt(max(0, s * (s - a) * (s - b) * (s - c)))

            # Circumradius R = abc/(4*Area)
            if area > 1e-9:
                R = (a * b * c) / (4 * area)
            else:
                R = float('inf')

            radii.append(R)

        radii.append(float('inf'))  # Last point

        return radii

    def _fetch_elevations(self, coordinates: List[Tuple[float, float]]) -> List[float]:
        """
        Fetch elevation data using Open-Meteo API (matching HTML lines 225-269).

        Args:
            coordinates: List of (lat, lon) tuples

        Returns:
            List of elevation values in meters
        """
        elevations = []
        batch_size = 100  # API limit

        for i in range(0, len(coordinates), batch_size):
            batch = coordinates[i:i + batch_size]

            # Check cache first
            uncached = []
            uncached_idx = []
            cached_results = [None] * len(batch)

            for j, (lat, lon) in enumerate(batch):
                cache_key = f"{lat:.6f},{lon:.6f}"
                if cache_key in self.elevation_cache:
                    cached_results[j] = self.elevation_cache[cache_key]
                else:
                    uncached.append((lat, lon))
                    uncached_idx.append(j)

            # Fetch uncached
            if uncached:
                lats = ','.join([str(c[0]) for c in uncached])
                lons = ','.join([str(c[1]) for c in uncached])
                url = f"https://api.open-meteo.com/v1/elevation?latitude={lats}&longitude={lons}"

                try:
                    response = requests.get(url, timeout=30)
                    response.raise_for_status()
                    data = response.json()

                    if 'elevation' in data:
                        for j, elev in enumerate(data['elevation']):
                            idx = uncached_idx[j]
                            cached_results[idx] = elev

                            # Cache
                            lat, lon = uncached[j]
                            cache_key = f"{lat:.6f},{lon:.6f}"
                            self.elevation_cache[cache_key] = elev

                    # Rate limiting (wait 2s between batches)
                    if i + batch_size < len(coordinates):
                        time.sleep(2)

                except Exception as e:
                    print(f"[WARN] Elevation API error: {e}")
                    # Fill with zeros on error
                    for idx in uncached_idx:
                        cached_results[idx] = 0.0

            elevations.extend(cached_results)

        return elevations


def main():
    """Test the KML analyzer with a sample file."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python kml_analyzer.py <kml_file>")
        sys.exit(1)

    kml_file = sys.argv[1]

    print(f"Analyzing: {kml_file}\n")

    analyzer = KMLAnalyzer(geom_step=10.0, smoothing_window=7)
    features = analyzer.analyze_kml(kml_file)

    print("="*60)
    print("STAGE FEATURES")
    print("="*60)
    print(f"\nDistance: {features['distance_km']:.2f} km")
    print(f"\nCurvature Features:")
    print(f"  Curvature Density: {features['curvature_density']:.3f} 1/km")
    print(f"  P95 Curvature: {features['p95_curvature']:.4f} 1/m")
    print(f"  Max Curvature: {features['max_curvature']:.4f} 1/m")
    print(f"\nHairpin Features:")
    print(f"  Hairpin Count: {features['hairpin_count']}")
    print(f"  Hairpin Density: {features['hairpin_density']:.2f} /km")
    print(f"\nDirectional Changes:")
    print(f"  Sign Changes: {features['sign_changes']}")
    print(f"  Sign Changes/km: {features['sign_changes_per_km']:.2f}")
    print(f"  Avg Turn Length: {features['avg_turn_length']:.1f} m")
    print(f"\nMetadata:")
    print(f"  Geometry Samples: {features['geometry_samples']}")


if __name__ == "__main__":
    main()
