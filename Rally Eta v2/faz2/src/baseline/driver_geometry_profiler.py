"""
Driver Geometry Profiler.

Analyzes driver performance characteristics on different stage geometries.
Creates lifetime profiles for hairpin, climb, and curvature performance.
"""
import sqlite3
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DriverGeometryProfile:
    """Driver's geometric performance profile."""
    driver_id: str
    driver_name: str

    # Sample sizes
    total_stages: int
    stages_with_geometry: int

    # Hairpin performance
    # > 1.0 means driver is slower on hairpin-heavy stages
    # < 1.0 means driver is faster on hairpin-heavy stages
    hairpin_performance: Optional[float]
    hairpin_high_stages: int   # Stages with high hairpin density
    hairpin_low_stages: int    # Stages with low hairpin density

    # Climb performance
    climb_performance: Optional[float]
    climb_high_stages: int
    climb_low_stages: int

    # Curvature sensitivity
    curvature_sensitivity: Optional[float]
    curvy_stages: int
    straight_stages: int

    # Grade performance
    grade_performance: Optional[float]
    steep_stages: int
    flat_stages: int

    # Confidence
    confidence: str  # HIGH, MEDIUM, LOW


class DriverGeometryProfiler:
    """
    Analyze driver performance on different geometric characteristics.

    Creates lifetime profiles by comparing performance on:
    - High hairpin vs low hairpin stages
    - High climb vs low climb stages
    - Curvy vs straight stages
    - Steep vs flat stages
    """

    # Thresholds for categorization
    HAIRPIN_DENSITY_THRESHOLD = 0.8  # hairpins per km
    CLIMB_THRESHOLD = 300  # meters total ascent
    CURVATURE_THRESHOLD = 0.005  # p95 curvature
    GRADE_THRESHOLD = 8  # max grade percentage

    # Minimum stages for reliable profile
    MIN_STAGES_HIGH = 5
    MIN_STAGES_LOW = 5

    def __init__(self, db_path: str):
        """
        Initialize profiler.

        Args:
            db_path: Path to database
        """
        self.db_path = db_path

    def create_profile(self, driver_id: str) -> Optional[DriverGeometryProfile]:
        """
        Create geometry performance profile for a driver.

        Uses ALL career data to build lifetime characteristics.

        Args:
            driver_id: Driver identifier

        Returns:
            DriverGeometryProfile or None if insufficient data
        """
        # Get driver stages with geometry data
        stages = self._get_driver_stages_with_geometry(driver_id)

        if len(stages) < 10:
            logger.warning(f"Insufficient data for driver {driver_id}: {len(stages)} stages")
            return None

        driver_name = stages[0]['driver_name'] if stages else driver_id

        # Categorize stages
        hairpin_high = [s for s in stages if s['hairpin_density'] and
                       s['hairpin_density'] > self.HAIRPIN_DENSITY_THRESHOLD]
        hairpin_low = [s for s in stages if s['hairpin_density'] and
                      s['hairpin_density'] <= self.HAIRPIN_DENSITY_THRESHOLD]

        climb_high = [s for s in stages if s['total_ascent'] and
                     s['total_ascent'] > self.CLIMB_THRESHOLD]
        climb_low = [s for s in stages if s['total_ascent'] and
                    s['total_ascent'] <= self.CLIMB_THRESHOLD]

        curvy = [s for s in stages if s['p95_curvature'] and
                s['p95_curvature'] > self.CURVATURE_THRESHOLD]
        straight = [s for s in stages if s['p95_curvature'] and
                   s['p95_curvature'] <= self.CURVATURE_THRESHOLD]

        steep = [s for s in stages if s['max_grade'] and
                s['max_grade'] > self.GRADE_THRESHOLD]
        flat = [s for s in stages if s['max_grade'] and
               s['max_grade'] <= self.GRADE_THRESHOLD]

        # Calculate performance ratios
        hairpin_perf = self._calculate_performance_ratio(hairpin_high, hairpin_low)
        climb_perf = self._calculate_performance_ratio(climb_high, climb_low)
        curv_perf = self._calculate_performance_ratio(curvy, straight)
        grade_perf = self._calculate_performance_ratio(steep, flat)

        # Determine confidence
        confidence = self._assess_confidence(
            len(hairpin_high), len(hairpin_low),
            len(climb_high), len(climb_low)
        )

        return DriverGeometryProfile(
            driver_id=driver_id,
            driver_name=driver_name,
            total_stages=len(stages),
            stages_with_geometry=len([s for s in stages if s['hairpin_density']]),

            hairpin_performance=hairpin_perf,
            hairpin_high_stages=len(hairpin_high),
            hairpin_low_stages=len(hairpin_low),

            climb_performance=climb_perf,
            climb_high_stages=len(climb_high),
            climb_low_stages=len(climb_low),

            curvature_sensitivity=curv_perf,
            curvy_stages=len(curvy),
            straight_stages=len(straight),

            grade_performance=grade_perf,
            steep_stages=len(steep),
            flat_stages=len(flat),

            confidence=confidence
        )

    def _get_driver_stages_with_geometry(self, driver_id: str) -> List[Dict]:
        """
        Get all driver stages joined with geometry data.

        Returns:
            List of stage results with geometry columns
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT
                COALESCE(sr.raw_driver_name, sr.driver_name) as driver_name,
                sr.rally_id,
                sr.stage_number,
                sr.time_seconds,
                sr.ratio_to_class_best,
                sm.distance_km,
                sm.hairpin_count,
                sm.hairpin_density,
                sm.total_ascent,
                sm.total_descent,
                sm.max_grade,
                sm.avg_abs_grade,
                sm.p95_curvature,
                sm.curvature_density,
                sm.straight_percentage,
                sm.curvy_percentage
            FROM stage_results sr
            LEFT JOIN stages_metadata sm
                ON sm.stage_id = COALESCE(sr.stage_id, sr.rally_id || '_ss' || sr.stage_number)
            WHERE COALESCE(sr.driver_id, sr.driver_name) = ?
            AND sr.time_seconds > 0
            AND sr.ratio_to_class_best IS NOT NULL
        """

        cursor.execute(query, [driver_id])
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def _calculate_performance_ratio(self, high_group: List[Dict],
                                     low_group: List[Dict]) -> Optional[float]:
        """
        Calculate performance ratio between two groups.

        Returns:
            high_avg / low_avg
            > 1.0 = worse on high-characteristic stages
            < 1.0 = better on high-characteristic stages
            None if insufficient data
        """
        if len(high_group) < self.MIN_STAGES_HIGH or len(low_group) < self.MIN_STAGES_LOW:
            return None

        high_ratios = [s['ratio_to_class_best'] for s in high_group
                      if s['ratio_to_class_best'] is not None]
        low_ratios = [s['ratio_to_class_best'] for s in low_group
                     if s['ratio_to_class_best'] is not None]

        if not high_ratios or not low_ratios:
            return None

        high_avg = sum(high_ratios) / len(high_ratios)
        low_avg = sum(low_ratios) / len(low_ratios)

        if low_avg == 0:
            return None

        return high_avg / low_avg

    def _assess_confidence(self, hairpin_high: int, hairpin_low: int,
                          climb_high: int, climb_low: int) -> str:
        """Assess profile confidence based on sample sizes."""
        min_samples = min(hairpin_high, hairpin_low, climb_high, climb_low)

        if min_samples >= 15:
            return 'HIGH'
        elif min_samples >= 10:
            return 'MEDIUM'
        elif min_samples >= 5:
            return 'LOW'
        else:
            return 'INSUFFICIENT'

    def get_profile_explanation(self, profile: DriverGeometryProfile) -> str:
        """
        Generate human-readable explanation of profile.

        Args:
            profile: DriverGeometryProfile

        Returns:
            Formatted explanation string
        """
        explanation = f"""
DRIVER GEOMETRY PROFILE - {profile.driver_name}
{'=' * 60}

Data:
  • Total stages: {profile.total_stages}
  • Stages with geometry: {profile.stages_with_geometry}
  • Confidence: {profile.confidence}

HAIRPIN PERFORMANCE
{'─' * 40}
"""

        if profile.hairpin_performance:
            diff = (profile.hairpin_performance - 1) * 100
            direction = "slower" if diff > 0 else "faster"
            explanation += f"""  • High hairpin stages: {profile.hairpin_high_stages}
  • Low hairpin stages: {profile.hairpin_low_stages}
  • Performance ratio: {profile.hairpin_performance:.3f}
  • Interpretation: {abs(diff):.1f}% {direction} on hairpin-heavy stages
"""
        else:
            explanation += "  • Insufficient data for hairpin analysis\n"

        explanation += f"""
CLIMB PERFORMANCE
{'─' * 40}
"""

        if profile.climb_performance:
            diff = (profile.climb_performance - 1) * 100
            direction = "slower" if diff > 0 else "faster"
            explanation += f"""  • High climb stages: {profile.climb_high_stages}
  • Low climb stages: {profile.climb_low_stages}
  • Performance ratio: {profile.climb_performance:.3f}
  • Interpretation: {abs(diff):.1f}% {direction} on climb-heavy stages
"""
        else:
            explanation += "  • Insufficient data for climb analysis\n"

        explanation += f"""
CURVATURE SENSITIVITY
{'─' * 40}
"""

        if profile.curvature_sensitivity:
            diff = (profile.curvature_sensitivity - 1) * 100
            direction = "slower" if diff > 0 else "faster"
            explanation += f"""  • Curvy stages: {profile.curvy_stages}
  • Straight stages: {profile.straight_stages}
  • Sensitivity ratio: {profile.curvature_sensitivity:.3f}
  • Interpretation: {abs(diff):.1f}% {direction} on curvy stages
"""
        else:
            explanation += "  • Insufficient data for curvature analysis\n"

        explanation += f"""
GRADE PERFORMANCE
{'─' * 40}
"""

        if profile.grade_performance:
            diff = (profile.grade_performance - 1) * 100
            direction = "slower" if diff > 0 else "faster"
            explanation += f"""  • Steep stages: {profile.steep_stages}
  • Flat stages: {profile.flat_stages}
  • Performance ratio: {profile.grade_performance:.3f}
  • Interpretation: {abs(diff):.1f}% {direction} on steep stages
"""
        else:
            explanation += "  • Insufficient data for grade analysis\n"

        # Summary
        explanation += f"""
{'=' * 60}
SUMMARY
{'=' * 60}
"""

        strengths = []
        weaknesses = []

        if profile.hairpin_performance:
            if profile.hairpin_performance < 0.99:
                strengths.append("Hairpins")
            elif profile.hairpin_performance > 1.01:
                weaknesses.append("Hairpins")

        if profile.climb_performance:
            if profile.climb_performance < 0.99:
                strengths.append("Climbs")
            elif profile.climb_performance > 1.01:
                weaknesses.append("Climbs")

        if profile.curvature_sensitivity:
            if profile.curvature_sensitivity < 0.99:
                strengths.append("Curvy sections")
            elif profile.curvature_sensitivity > 1.01:
                weaknesses.append("Curvy sections")

        if profile.grade_performance:
            if profile.grade_performance < 0.99:
                strengths.append("Steep grades")
            elif profile.grade_performance > 1.01:
                weaknesses.append("Steep grades")

        if strengths:
            explanation += f"  Strengths: {', '.join(strengths)}\n"
        else:
            explanation += "  Strengths: None identified\n"

        if weaknesses:
            explanation += f"  Weaknesses: {', '.join(weaknesses)}\n"
        else:
            explanation += "  Weaknesses: None identified\n"

        return explanation

    def to_dict(self, profile: DriverGeometryProfile) -> Dict:
        """Convert profile to dictionary for database storage or JSON."""
        return {
            'driver_id': profile.driver_id,
            'driver_name': profile.driver_name,
            'total_stages': profile.total_stages,
            'stages_with_geometry': profile.stages_with_geometry,
            'hairpin_performance': profile.hairpin_performance,
            'hairpin_high_stages': profile.hairpin_high_stages,
            'hairpin_low_stages': profile.hairpin_low_stages,
            'climb_performance': profile.climb_performance,
            'climb_high_stages': profile.climb_high_stages,
            'climb_low_stages': profile.climb_low_stages,
            'curvature_sensitivity': profile.curvature_sensitivity,
            'curvy_stages': profile.curvy_stages,
            'straight_stages': profile.straight_stages,
            'grade_performance': profile.grade_performance,
            'steep_stages': profile.steep_stages,
            'flat_stages': profile.flat_stages,
            'confidence': profile.confidence
        }


def main():
    """Test driver geometry profiler."""
    import argparse

    parser = argparse.ArgumentParser(description="Driver geometry profiler")
    parser.add_argument('--db-path', default='data/raw/rally_results.db',
                       help='Database path')
    parser.add_argument('--driver-id', required=True, help='Driver ID')

    args = parser.parse_args()

    profiler = DriverGeometryProfiler(args.db_path)
    profile = profiler.create_profile(args.driver_id)

    if profile:
        explanation = profiler.get_profile_explanation(profile)
        print(explanation)
    else:
        print(f"Could not create profile for {args.driver_id}")
        print("Possible reasons: insufficient data or no geometry data available")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
