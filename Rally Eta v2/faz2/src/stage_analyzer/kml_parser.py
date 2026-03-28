"""
KML/KMZ Multi-Stage Parser
Extracts multiple stages from a single KML/KMZ file
"""

import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple
from pathlib import Path
import zipfile
import logging

logger = logging.getLogger(__name__)


class Stage:
    """Represents a single rally stage"""

    def __init__(self, name: str, coordinates: List[Tuple[float, float]], properties: Dict = None):
        self.name = name
        self.coordinates = coordinates  # List of (lat, lon) tuples
        self.properties = properties or {}

    def __repr__(self):
        return f"Stage(name='{self.name}', points={len(self.coordinates)})"


class KMLParser:
    """Parse KML/KMZ files and extract multiple stages"""

    # KML namespace
    NS = {'kml': 'http://www.opengis.net/kml/2.2'}

    def parse_file(self, file_path: str) -> List[Stage]:
        """
        Parse KML or KMZ file and extract all stages (LineStrings)

        Args:
            file_path: Path to KML or KMZ file

        Returns:
            List of Stage objects
        """
        file_path = Path(file_path)

        if file_path.suffix.lower() == '.kmz':
            kml_content = self._extract_kml_from_kmz(file_path)
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                kml_content = f.read()

        return self._parse_kml_content(kml_content)

    def _extract_kml_from_kmz(self, kmz_path: Path) -> str:
        """Extract KML content from KMZ archive"""
        with zipfile.ZipFile(kmz_path, 'r') as kmz:
            # Find .kml file in archive
            kml_files = [name for name in kmz.namelist() if name.lower().endswith('.kml')]

            if not kml_files:
                raise ValueError(f"No KML file found in KMZ: {kmz_path}")

            # Use first KML file
            kml_filename = kml_files[0]
            logger.info(f"Extracting {kml_filename} from KMZ")

            with kmz.open(kml_filename) as kml_file:
                return kml_file.read().decode('utf-8')

    def _parse_kml_content(self, kml_content: str) -> List[Stage]:
        """Parse KML XML content and extract stages"""
        try:
            root = ET.fromstring(kml_content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid KML content: {e}")

        stages = []

        # Find all Placemarks
        placemarks = root.findall('.//kml:Placemark', self.NS)

        if not placemarks:
            # Try without namespace (some KML files don't use it)
            placemarks = root.findall('.//Placemark')

        for placemark in placemarks:
            stage = self._parse_placemark(placemark)
            if stage:
                stages.append(stage)

        logger.info(f"Extracted {len(stages)} stage(s) from KML")
        return stages

    def _parse_placemark(self, placemark: ET.Element) -> Stage:
        """Parse a single Placemark element"""
        # Get name
        name_elem = placemark.find('kml:name', self.NS)
        if name_elem is None:
            name_elem = placemark.find('name')

        name = name_elem.text if name_elem is not None else "Unnamed Stage"

        # Get LineString coordinates
        linestring = placemark.find('.//kml:LineString/kml:coordinates', self.NS)
        if linestring is None:
            linestring = placemark.find('.//LineString/coordinates')

        if linestring is None:
            # Not a LineString, skip
            return None

        # Parse coordinates
        coords_text = linestring.text.strip()
        coordinates = self._parse_coordinates(coords_text)

        if not coordinates:
            logger.warning(f"No valid coordinates for placemark: {name}")
            return None

        # Get properties (ExtendedData)
        properties = self._parse_extended_data(placemark)

        return Stage(name=name, coordinates=coordinates, properties=properties)

    def _parse_coordinates(self, coords_text: str) -> List[Tuple[float, float]]:
        """
        Parse KML coordinates string
        Format: "lon,lat,alt lon,lat,alt ..." or "lon,lat lon,lat ..."
        """
        coordinates = []

        # Split by whitespace or newline
        coord_tuples = coords_text.split()

        for coord_str in coord_tuples:
            parts = coord_str.strip().split(',')

            if len(parts) >= 2:
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    # altitude = float(parts[2]) if len(parts) > 2 else 0

                    coordinates.append((lat, lon))  # Return as (lat, lon)
                except ValueError:
                    continue

        return coordinates

    def _parse_extended_data(self, placemark: ET.Element) -> Dict:
        """Parse ExtendedData for additional properties"""
        properties = {}

        extended_data = placemark.find('kml:ExtendedData', self.NS)
        if extended_data is None:
            extended_data = placemark.find('ExtendedData')

        if extended_data is not None:
            # Parse Data elements
            for data in extended_data.findall('kml:Data', self.NS):
                name = data.get('name')
                value_elem = data.find('kml:value', self.NS)
                if name and value_elem is not None:
                    properties[name] = value_elem.text

            # Try without namespace
            for data in extended_data.findall('Data'):
                name = data.get('name')
                value_elem = data.find('value')
                if name and value_elem is not None:
                    properties[name] = value_elem.text

        return properties


def parse_kml_file(file_path: str) -> List[Stage]:
    """
    Convenience function to parse KML/KMZ file

    Args:
        file_path: Path to KML or KMZ file

    Returns:
        List of Stage objects
    """
    parser = KMLParser()
    return parser.parse_file(file_path)
