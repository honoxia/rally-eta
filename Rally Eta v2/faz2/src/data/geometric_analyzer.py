"""
Geometric analysis of rally stage routes.

Calculates:
- Hairpin count and density
- Curvature metrics
- Grade (slope) analysis
- Turn classification
"""
import logging
import math
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from src.data.kml_parser import KMLParser, KMLData, Coordinate

logger = logging.getLogger(__name__)


def _mean(values: List[float]) -> float:
    """Return arithmetic mean using stdlib only."""
    return sum(values) / len(values) if values else 0.0


def _percentile(values: List[float], percentile: float) -> float:
    """Return percentile with linear interpolation and no numpy dependency."""
    if not values:
        return 0.0

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    rank = (percentile / 100.0) * (len(ordered) - 1)
    lower_index = int(math.floor(rank))
    upper_index = int(math.ceil(rank))

    if lower_index == upper_index:
        return ordered[lower_index]

    lower_value = ordered[lower_index]
    upper_value = ordered[upper_index]
    fraction = rank - lower_index
    return lower_value + ((upper_value - lower_value) * fraction)


@dataclass
class StageGeometry:
    """Complete geometric analysis of a stage."""
    # Basic info
    name: str
    distance_km: float

    # Elevation
    total_ascent: float       # meters
    total_descent: float      # meters
    min_altitude: float
    max_altitude: float
    elevation_gain: float     # max - min

    # Grade (slope)
    max_grade: float          # maximum slope percentage
    avg_grade: float          # average slope
    avg_abs_grade: float      # average absolute slope

    # Turns and hairpins
    hairpin_count: int        # sharp turns (> 120 degrees)
    turn_count: int           # all significant turns (> 45 degrees)
    hairpin_density: float    # hairpins per km
    turn_density: float       # turns per km

    # Curvature
    avg_curvature: float      # average curvature (1/radius)
    max_curvature: float      # maximum curvature
    p95_curvature: float      # 95th percentile curvature
    curvature_density: float  # high-curvature sections per km

    # Segment analysis
    straight_percentage: float   # % of route that is straight
    curvy_percentage: float      # % of route with high curvature


class GeometricAnalyzer:
    """
    Analyze rally stage geometry from coordinates.

    Calculates hairpins, curvature, grade, and other metrics
    relevant for rally performance prediction.
    """

    # Thresholds for turn detection
    HAIRPIN_ANGLE_THRESHOLD = 120    # degrees - sharp hairpin
    TURN_ANGLE_THRESHOLD = 45        # degrees - significant turn
    MIN_SEGMENT_LENGTH = 10          # meters - minimum segment for analysis

    # Curvature thresholds
    HIGH_CURVATURE_THRESHOLD = 0.01  # 1/100m radius = sharp turn
    STRAIGHT_CURVATURE_THRESHOLD = 0.001  # nearly straight

    def __init__(self):
        self.kml_parser = KMLParser()

    def analyze(self, coords: List[Coordinate]) -> Optional[StageGeometry]:
        """
        Analyze a list of coordinates directly.

        Args:
            coords: List of Coordinate objects

        Returns:
            StageGeometry with all calculated metrics
        """
        if len(coords) < 3:
            logger.warning(f"Insufficient coordinates for analysis: {len(coords)}")
            return None

        # Create a minimal KMLData-like structure
        # Calculate basic metrics from coordinates
        distance_km = self._calculate_total_distance(coords)
        total_ascent, total_descent = self._calculate_elevation_changes(coords)
        altitudes = [c.altitude for c in coords if c.altitude != 0]
        min_alt = min(altitudes) if altitudes else 0
        max_alt = max(altitudes) if altitudes else 0

        # Create a mock KMLData for analyze_coordinates
        from src.data.kml_parser import KMLData
        kml_data = KMLData(
            name="Stage",
            coordinates=coords,
            distance_km=distance_km,
            total_ascent=total_ascent,
            total_descent=total_descent,
            min_altitude=min_alt,
            max_altitude=max_alt
        )

        return self.analyze_coordinates(kml_data)

    def _calculate_total_distance(self, coords: List[Coordinate]) -> float:
        """Calculate total distance in km from coordinate list."""
        total = 0.0
        for i in range(1, len(coords)):
            total += self._haversine_meters(
                coords[i-1].latitude, coords[i-1].longitude,
                coords[i].latitude, coords[i].longitude
            )
        return total / 1000.0

    def _calculate_elevation_changes(self, coords: List[Coordinate]) -> Tuple[float, float]:
        """Calculate total ascent and descent from coordinates."""
        ascent = 0.0
        descent = 0.0
        coords_with_alt = [c for c in coords if c.altitude != 0]

        for i in range(1, len(coords_with_alt)):
            diff = coords_with_alt[i].altitude - coords_with_alt[i-1].altitude
            if diff > 0:
                ascent += diff
            else:
                descent += abs(diff)

        return ascent, descent

    def analyze_file(self, file_path: str) -> Optional[StageGeometry]:
        """
        Analyze a KML/KMZ file.

        Args:
            file_path: Path to KML or KMZ file

        Returns:
            StageGeometry with all calculated metrics
        """
        kml_data = self.kml_parser.parse(file_path)

        if not kml_data:
            return None

        return self.analyze_coordinates(kml_data)

    def analyze_coordinates(self, kml_data: KMLData) -> Optional[StageGeometry]:
        """
        Analyze coordinates to extract geometric features.

        Args:
            kml_data: Parsed KML data

        Returns:
            StageGeometry with all metrics
        """
        coords = kml_data.coordinates

        if len(coords) < 3:
            logger.warning(f"Insufficient coordinates for analysis: {len(coords)}")
            return None

        # Calculate grade metrics
        grades = self._calculate_grades(coords)
        max_grade = max(grades) if grades else 0
        min_grade = min(grades) if grades else 0
        avg_grade = _mean(grades) if grades else 0
        avg_abs_grade = _mean([abs(g) for g in grades]) if grades else 0

        # Calculate turn angles
        turn_angles = self._calculate_turn_angles(coords)

        # Count hairpins and turns
        hairpin_count = sum(1 for angle in turn_angles if angle > self.HAIRPIN_ANGLE_THRESHOLD)
        turn_count = sum(1 for angle in turn_angles if angle > self.TURN_ANGLE_THRESHOLD)

        # Calculate curvature
        curvatures = self._calculate_curvatures(coords)

        avg_curvature = _mean(curvatures) if curvatures else 0
        max_curvature = max(curvatures) if curvatures else 0
        p95_curvature = _percentile(curvatures, 95) if curvatures else 0

        # Calculate segment percentages
        straight_pct, curvy_pct = self._calculate_segment_percentages(curvatures)

        # High curvature sections count
        high_curv_sections = sum(1 for c in curvatures if c > self.HIGH_CURVATURE_THRESHOLD)
        curvature_density = high_curv_sections / kml_data.distance_km if kml_data.distance_km > 0 else 0

        # Density calculations
        hairpin_density = hairpin_count / kml_data.distance_km if kml_data.distance_km > 0 else 0
        turn_density = turn_count / kml_data.distance_km if kml_data.distance_km > 0 else 0

        return StageGeometry(
            name=kml_data.name,
            distance_km=kml_data.distance_km,

            # Elevation
            total_ascent=kml_data.total_ascent,
            total_descent=kml_data.total_descent,
            min_altitude=kml_data.min_altitude,
            max_altitude=kml_data.max_altitude,
            elevation_gain=kml_data.max_altitude - kml_data.min_altitude,

            # Grade
            max_grade=max_grade,
            avg_grade=avg_grade,
            avg_abs_grade=avg_abs_grade,

            # Turns
            hairpin_count=hairpin_count,
            turn_count=turn_count,
            hairpin_density=hairpin_density,
            turn_density=turn_density,

            # Curvature
            avg_curvature=avg_curvature,
            max_curvature=max_curvature,
            p95_curvature=p95_curvature,
            curvature_density=curvature_density,

            # Segments
            straight_percentage=straight_pct,
            curvy_percentage=curvy_pct
        )

    def _calculate_grades(self, coords: List[Coordinate]) -> List[float]:
        """
        Calculate grade (slope) between consecutive points.

        Returns list of grade percentages.
        """
        grades = []

        coords_with_alt = [c for c in coords if c.altitude != 0]

        if len(coords_with_alt) < 2:
            return grades

        for i in range(1, len(coords_with_alt)):
            prev = coords_with_alt[i - 1]
            curr = coords_with_alt[i]

            # Horizontal distance
            h_dist = self._haversine_meters(
                prev.latitude, prev.longitude,
                curr.latitude, curr.longitude
            )

            # Vertical change
            v_change = curr.altitude - prev.altitude

            # Grade as percentage
            if h_dist > 0:
                grade = (v_change / h_dist) * 100
                grades.append(grade)

        return grades

    def _calculate_turn_angles(self, coords: List[Coordinate]) -> List[float]:
        """
        Calculate turn angles at each point.

        Returns list of angles in degrees (0 = straight, 180 = U-turn).
        """
        angles = []

        if len(coords) < 3:
            return angles

        for i in range(1, len(coords) - 1):
            prev = coords[i - 1]
            curr = coords[i]
            next_pt = coords[i + 1]

            # Bearing from prev to curr
            bearing1 = self._calculate_bearing(
                prev.latitude, prev.longitude,
                curr.latitude, curr.longitude
            )

            # Bearing from curr to next
            bearing2 = self._calculate_bearing(
                curr.latitude, curr.longitude,
                next_pt.latitude, next_pt.longitude
            )

            # Turn angle (change in bearing)
            angle = abs(bearing2 - bearing1)

            # Normalize to 0-180
            if angle > 180:
                angle = 360 - angle

            angles.append(angle)

        return angles

    def _calculate_curvatures(self, coords: List[Coordinate]) -> List[float]:
        """
        Calculate curvature at each point using three-point method.

        Curvature = 1/radius (higher = sharper turn)
        """
        curvatures = []

        if len(coords) < 3:
            return curvatures

        for i in range(1, len(coords) - 1):
            prev = coords[i - 1]
            curr = coords[i]
            next_pt = coords[i + 1]

            # Convert to local XY coordinates (meters)
            x1, y1 = self._to_local_xy(prev, curr)
            x2, y2 = 0, 0  # curr is origin
            x3, y3 = self._to_local_xy(next_pt, curr)

            # Calculate curvature using circumradius formula
            curvature = self._three_point_curvature(x1, y1, x2, y2, x3, y3)
            curvatures.append(curvature)

        return curvatures

    def _three_point_curvature(self, x1, y1, x2, y2, x3, y3) -> float:
        """
        Calculate curvature using three points.

        Uses the formula: k = 4*Area / (|P1-P2| * |P2-P3| * |P3-P1|)
        """
        # Side lengths
        a = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        b = math.sqrt((x3 - x2)**2 + (y3 - y2)**2)
        c = math.sqrt((x3 - x1)**2 + (y3 - y1)**2)

        # Area using cross product
        area = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2

        # Avoid division by zero
        denominator = a * b * c

        if denominator < 0.001:
            return 0.0

        # Curvature = 4 * Area / (a * b * c)
        curvature = 4 * area / denominator

        return curvature

    def _calculate_bearing(self, lat1: float, lon1: float,
                          lat2: float, lon2: float) -> float:
        """Calculate bearing from point 1 to point 2 in degrees."""
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lon = math.radians(lon2 - lon1)

        x = math.sin(delta_lon) * math.cos(lat2_rad)
        y = (math.cos(lat1_rad) * math.sin(lat2_rad) -
             math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon))

        bearing = math.atan2(x, y)
        bearing = math.degrees(bearing)

        # Normalize to 0-360
        bearing = (bearing + 360) % 360

        return bearing

    def _haversine_meters(self, lat1: float, lon1: float,
                         lat2: float, lon2: float) -> float:
        """Calculate distance in meters using Haversine formula."""
        R = 6371000  # Earth's radius in meters

        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lon / 2) ** 2)

        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def _to_local_xy(self, point: Coordinate, origin: Coordinate) -> Tuple[float, float]:
        """Convert coordinate to local XY (meters) relative to origin."""
        # X is east-west distance
        x = self._haversine_meters(
            origin.latitude, origin.longitude,
            origin.latitude, point.longitude
        )
        if point.longitude < origin.longitude:
            x = -x

        # Y is north-south distance
        y = self._haversine_meters(
            origin.latitude, origin.longitude,
            point.latitude, origin.longitude
        )
        if point.latitude < origin.latitude:
            y = -y

        return x, y

    def _calculate_segment_percentages(self, curvatures: List[float]) -> Tuple[float, float]:
        """
        Calculate percentage of straight vs curvy segments.

        Returns:
            (straight_percentage, curvy_percentage)
        """
        if not curvatures:
            return 0.0, 0.0

        straight_count = sum(1 for c in curvatures if c < self.STRAIGHT_CURVATURE_THRESHOLD)
        curvy_count = sum(1 for c in curvatures if c > self.HIGH_CURVATURE_THRESHOLD)

        total = len(curvatures)

        straight_pct = (straight_count / total) * 100
        curvy_pct = (curvy_count / total) * 100

        return straight_pct, curvy_pct

    def to_dict(self, geometry: StageGeometry) -> Dict:
        """Convert StageGeometry to dictionary for database storage."""
        return {
            'name': geometry.name,
            'distance_km': geometry.distance_km,
            'total_ascent': geometry.total_ascent,
            'total_descent': geometry.total_descent,
            'min_altitude': geometry.min_altitude,
            'max_altitude': geometry.max_altitude,
            'elevation_gain': geometry.elevation_gain,
            'max_grade': geometry.max_grade,
            'avg_grade': geometry.avg_grade,
            'avg_abs_grade': geometry.avg_abs_grade,
            'hairpin_count': geometry.hairpin_count,
            'turn_count': geometry.turn_count,
            'hairpin_density': geometry.hairpin_density,
            'turn_density': geometry.turn_density,
            'avg_curvature': geometry.avg_curvature,
            'max_curvature': geometry.max_curvature,
            'p95_curvature': geometry.p95_curvature,
            'curvature_density': geometry.curvature_density,
            'straight_percentage': geometry.straight_percentage,
            'curvy_percentage': geometry.curvy_percentage
        }


def main():
    """Test geometric analyzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Analyze rally stage geometry")
    parser.add_argument('file', help='KML or KMZ file to analyze')

    args = parser.parse_args()

    analyzer = GeometricAnalyzer()
    geometry = analyzer.analyze_file(args.file)

    if geometry:
        print(f"\nStage Geometry: {geometry.name}")
        print("=" * 60)
        print(f"\nBasic Info:")
        print(f"  Distance: {geometry.distance_km:.2f} km")

        print(f"\nElevation:")
        print(f"  Total Ascent: {geometry.total_ascent:.0f} m")
        print(f"  Total Descent: {geometry.total_descent:.0f} m")
        print(f"  Elevation Range: {geometry.min_altitude:.0f} - {geometry.max_altitude:.0f} m")
        print(f"  Elevation Gain: {geometry.elevation_gain:.0f} m")

        print(f"\nGrade (Slope):")
        print(f"  Max Grade: {geometry.max_grade:.1f}%")
        print(f"  Avg Grade: {geometry.avg_grade:.1f}%")
        print(f"  Avg Absolute Grade: {geometry.avg_abs_grade:.1f}%")

        print(f"\nTurns:")
        print(f"  Hairpin Count: {geometry.hairpin_count}")
        print(f"  Turn Count: {geometry.turn_count}")
        print(f"  Hairpin Density: {geometry.hairpin_density:.2f} per km")
        print(f"  Turn Density: {geometry.turn_density:.2f} per km")

        print(f"\nCurvature:")
        print(f"  Avg Curvature: {geometry.avg_curvature:.4f}")
        print(f"  Max Curvature: {geometry.max_curvature:.4f}")
        print(f"  P95 Curvature: {geometry.p95_curvature:.4f}")
        print(f"  Curvature Density: {geometry.curvature_density:.2f} per km")

        print(f"\nSegments:")
        print(f"  Straight: {geometry.straight_percentage:.1f}%")
        print(f"  Curvy: {geometry.curvy_percentage:.1f}%")
    else:
        print("Failed to analyze file")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
