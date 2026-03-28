"""
KML/KMZ file parser for rally stage geometry extraction.
"""
import logging
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
import math

logger = logging.getLogger(__name__)


@dataclass
class Coordinate:
    """Single coordinate point."""
    latitude: float
    longitude: float
    altitude: float = 0.0


@dataclass
class KMLData:
    """Parsed KML data container."""
    name: str
    coordinates: List[Coordinate]
    distance_km: float
    total_ascent: float
    total_descent: float
    min_altitude: float
    max_altitude: float


class KMLParser:
    """
    Parse KML/KMZ files to extract rally stage geometry.

    Supports:
    - .kml files (plain XML)
    - .kmz files (compressed KML)

    Example:
        >>> parser = KMLParser()
        >>> data = parser.parse('stage_ss1.kml')
        >>> print(f"Distance: {data.distance_km:.2f} km")
        >>> print(f"Total ascent: {data.total_ascent:.0f} m")
    """

    # KML namespace
    KML_NS = {
        'kml': 'http://www.opengis.net/kml/2.2',
        'gx': 'http://www.google.com/kml/ext/2.2'
    }

    def parse(self, file_path: str) -> Optional[KMLData]:
        """
        Parse a KML or KMZ file.

        Args:
            file_path: Path to KML or KMZ file

        Returns:
            KMLData object with parsed geometry, or None if parsing fails
        """
        path = Path(file_path)

        if not path.exists():
            logger.error(f"File not found: {file_path}")
            return None

        # Handle KMZ (compressed) files
        if path.suffix.lower() == '.kmz':
            return self._parse_kmz(path)
        elif path.suffix.lower() == '.kml':
            return self._parse_kml(path)
        else:
            logger.error(f"Unsupported file format: {path.suffix}")
            return None

    def parse_multi(self, file_path: str) -> List[Dict]:
        """
        Parse a KML/KMZ file and return multiple stages if present.

        Returns:
            List of dicts with keys: name, coordinates, distance_km,
            total_ascent, total_descent, min_altitude, max_altitude
        """
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {file_path}")
            return []

        if path.suffix.lower() == '.kmz':
            try:
                with zipfile.ZipFile(path, 'r') as kmz:
                    kml_files = [f for f in kmz.namelist() if f.endswith('.kml')]
                    if not kml_files:
                        logger.error(f"No KML file found in KMZ: {path}")
                        return []
                    kml_content = kmz.read(kml_files[0])
                    return self._parse_kml_multi_content(kml_content, path.stem)
            except zipfile.BadZipFile:
                logger.error(f"Invalid KMZ file: {path}")
                return []

        if path.suffix.lower() == '.kml':
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return self._parse_kml_multi_content(content.encode('utf-8'), path.stem)
            except Exception as e:
                logger.error(f"Error reading KML file {path}: {e}")
                return []

        logger.error(f"Unsupported file format: {path.suffix}")
        return []

    def _parse_kmz(self, path: Path) -> Optional[KMLData]:
        """Parse KMZ (compressed KML) file."""
        try:
            with zipfile.ZipFile(path, 'r') as kmz:
                # Find the .kml file inside
                kml_files = [f for f in kmz.namelist() if f.endswith('.kml')]

                if not kml_files:
                    logger.error(f"No KML file found in KMZ: {path}")
                    return None

                # Read the first KML file
                kml_content = kmz.read(kml_files[0])
                return self._parse_kml_content(kml_content, path.stem)

        except zipfile.BadZipFile:
            logger.error(f"Invalid KMZ file: {path}")
            return None

    def _parse_kml(self, path: Path) -> Optional[KMLData]:
        """Parse plain KML file."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            return self._parse_kml_content(content.encode('utf-8'), path.stem)
        except Exception as e:
            logger.error(f"Error reading KML file {path}: {e}")
            return None

    def _parse_kml_content(self, content: bytes, default_name: str) -> Optional[KMLData]:
        """Parse KML XML content."""
        try:
            root = ET.fromstring(content)

            # Extract name
            name = self._extract_name(root) or default_name

            # Extract coordinates from all LineStrings
            coordinates = self._extract_all_coordinates(root)

            if not coordinates:
                logger.warning(f"No coordinates found in KML: {name}")
                return None

            # Calculate metrics
            distance_km = self._calculate_distance(coordinates)
            total_ascent, total_descent = self._calculate_elevation_change(coordinates)

            altitudes = [c.altitude for c in coordinates if c.altitude != 0]
            min_altitude = min(altitudes) if altitudes else 0
            max_altitude = max(altitudes) if altitudes else 0

            logger.info(f"Parsed KML '{name}': {len(coordinates)} points, {distance_km:.2f} km")

            return KMLData(
                name=name,
                coordinates=coordinates,
                distance_km=distance_km,
                total_ascent=total_ascent,
                total_descent=total_descent,
                min_altitude=min_altitude,
                max_altitude=max_altitude
            )

        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return None

    def _parse_kml_multi_content(self, content: bytes, default_name: str) -> List[Dict]:
        """Parse KML content into multiple stage entries (per Placemark)."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return []

        placemarks = []
        for elem in root.iter():
            if elem.tag.endswith('Placemark'):
                placemarks.append(elem)

        if not placemarks:
            single = self._parse_kml_content(content, default_name)
            if not single:
                return []
            return [{
                'name': single.name,
                'coordinates': single.coordinates,
                'distance_km': single.distance_km,
                'total_ascent': single.total_ascent,
                'total_descent': single.total_descent,
                'min_altitude': single.min_altitude,
                'max_altitude': single.max_altitude,
            }]

        stages = []
        for placemark in placemarks:
            name = None
            for ns_prefix in ['kml:', '']:
                name_elem = placemark.find(f'.//{ns_prefix}name', self.KML_NS)
                if name_elem is not None and name_elem.text:
                    name = name_elem.text.strip()
                    break
            if not name:
                name = default_name

            coords = []
            for coord_elem in placemark.iter():
                if coord_elem.tag.endswith('coordinates') and coord_elem.text:
                    coords.extend(self._parse_coordinates_text(coord_elem.text))

            if not coords:
                continue

            distance_km = self._calculate_distance(coords)
            total_ascent, total_descent = self._calculate_elevation_change(coords)

            altitudes = [c.altitude for c in coords if c.altitude != 0]
            min_altitude = min(altitudes) if altitudes else 0
            max_altitude = max(altitudes) if altitudes else 0

            stages.append({
                'name': name,
                'coordinates': coords,
                'distance_km': distance_km,
                'total_ascent': total_ascent,
                'total_descent': total_descent,
                'min_altitude': min_altitude,
                'max_altitude': max_altitude,
            })

        if not stages:
            single = self._parse_kml_content(content, default_name)
            if not single:
                return []
            return [{
                'name': single.name,
                'coordinates': single.coordinates,
                'distance_km': single.distance_km,
                'total_ascent': single.total_ascent,
                'total_descent': single.total_descent,
                'min_altitude': single.min_altitude,
                'max_altitude': single.max_altitude,
            }]

        return stages

    def _extract_name(self, root: ET.Element) -> Optional[str]:
        """Extract document/placemark name."""
        # Try Document name first
        for ns_prefix in ['kml:', '']:
            name_elem = root.find(f'.//{ns_prefix}Document/{ns_prefix}name', self.KML_NS)
            if name_elem is not None and name_elem.text:
                return name_elem.text.strip()

        # Try Placemark name
        for ns_prefix in ['kml:', '']:
            name_elem = root.find(f'.//{ns_prefix}Placemark/{ns_prefix}name', self.KML_NS)
            if name_elem is not None and name_elem.text:
                return name_elem.text.strip()

        return None

    def _extract_all_coordinates(self, root: ET.Element) -> List[Coordinate]:
        """Extract coordinates from all LineString elements."""
        all_coords = []

        # Find all coordinates elements (with or without namespace)
        for coord_elem in root.iter():
            if coord_elem.tag.endswith('coordinates') and coord_elem.text:
                coords = self._parse_coordinates_text(coord_elem.text)
                all_coords.extend(coords)

        return all_coords

    def _parse_coordinates_text(self, text: str) -> List[Coordinate]:
        """Parse coordinate text (lon,lat,alt lon,lat,alt ...)."""
        coordinates = []

        # Split by whitespace and newlines
        points = text.strip().split()

        for point in points:
            parts = point.strip().split(',')

            if len(parts) >= 2:
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    alt = float(parts[2]) if len(parts) >= 3 else 0.0

                    coordinates.append(Coordinate(
                        latitude=lat,
                        longitude=lon,
                        altitude=alt
                    ))
                except ValueError:
                    continue

        return coordinates

    def _calculate_distance(self, coordinates: List[Coordinate]) -> float:
        """Calculate total distance in kilometers using Haversine formula."""
        if len(coordinates) < 2:
            return 0.0

        total_distance = 0.0

        for i in range(1, len(coordinates)):
            prev = coordinates[i - 1]
            curr = coordinates[i]

            distance = self._haversine_distance(
                prev.latitude, prev.longitude,
                curr.latitude, curr.longitude
            )
            total_distance += distance

        return total_distance

    def _haversine_distance(self, lat1: float, lon1: float,
                           lat2: float, lon2: float) -> float:
        """
        Calculate distance between two points using Haversine formula.

        Returns distance in kilometers.
        """
        R = 6371.0  # Earth's radius in km

        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lon / 2) ** 2)

        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def _calculate_elevation_change(self, coordinates: List[Coordinate]) -> Tuple[float, float]:
        """
        Calculate total ascent and descent.

        Returns:
            (total_ascent, total_descent) in meters
        """
        if len(coordinates) < 2:
            return 0.0, 0.0

        total_ascent = 0.0
        total_descent = 0.0

        # Filter out zero-altitude points for elevation calculation
        coords_with_alt = [c for c in coordinates if c.altitude != 0]

        if len(coords_with_alt) < 2:
            return 0.0, 0.0

        for i in range(1, len(coords_with_alt)):
            prev_alt = coords_with_alt[i - 1].altitude
            curr_alt = coords_with_alt[i].altitude

            diff = curr_alt - prev_alt

            if diff > 0:
                total_ascent += diff
            else:
                total_descent += abs(diff)

        return total_ascent, total_descent


def main():
    """Test KML parser."""
    import argparse

    parser = argparse.ArgumentParser(description="Parse KML/KMZ files")
    parser.add_argument('file', help='KML or KMZ file to parse')

    args = parser.parse_args()

    kml_parser = KMLParser()
    data = kml_parser.parse(args.file)

    if data:
        print(f"\nKML Data: {data.name}")
        print("=" * 50)
        print(f"  Coordinates: {len(data.coordinates)} points")
        print(f"  Distance: {data.distance_km:.2f} km")
        print(f"  Total Ascent: {data.total_ascent:.0f} m")
        print(f"  Total Descent: {data.total_descent:.0f} m")
        print(f"  Altitude Range: {data.min_altitude:.0f} - {data.max_altitude:.0f} m")
    else:
        print("Failed to parse KML file")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
