"""
Car class normalization for TOSFED rally classes.
"""
import logging

logger = logging.getLogger(__name__)


class CarClassNormalizer:
    """
    Normalize TOSFED rally car class names.

    Examples:
        'R4' → 'Rally2'
        'S2000' → 'Rally2'
        'Rally 2' → 'Rally2'
        'rally3' → 'Rally3'
    """

    NORMALIZATION_MAP = {
        # Rally2 variants → 'Rally2'
        'rally2': 'Rally2',
        'rally 2': 'Rally2',
        'Rally 2': 'Rally2',
        'Rally2': 'Rally2',
        'Rally2 Kit': 'Rally2',
        'rally2 kit': 'Rally2',
        'VR4K': 'Rally2',
        'R4': 'Rally2',
        'VR4': 'Rally2',
        'NR4': 'Rally2',
        'Grup NR4': 'Rally2',
        'S2000': 'Rally2',
        'S2000-Rally': 'Rally2',
        'Sınıf N': 'Rally2',
        'Grup N 2000+': 'Rally2',

        # Rally3 variants → 'Rally3'
        'rally3': 'Rally3',
        'Rally 3': 'Rally3',
        'Rally3': 'Rally3',

        # Rally4 variants → 'Rally4'
        'rally4': 'Rally4',
        'Rally 4': 'Rally4',
        'Rally4': 'Rally4',
        'R2': 'Rally4',
        'Grup R2': 'Rally4',
        'R3': 'Rally4',
        'R3T': 'Rally4',
        'R3D': 'Rally4',
        'Grup A': 'Rally4',
        'Grup A 2000': 'Rally4',

        # Rally5 variants → 'Rally5'
        'rally5': 'Rally5',
        'Rally 5': 'Rally5',
        'Rally5': 'Rally5',
        'Rally5 Kit': 'Rally5',
        'R1': 'Rally5',
        'R1T': 'Rally5',

        # TOSFED Categories
        'Kategori 1': 'K1',
        'Kategori 2': 'K2',
        'Kategori 3': 'K3',
        'Kategori 4': 'K4',
        'H11': 'K1',
        'H12': 'K2',
        'H13': 'K3',
        'H14': 'K4',
        'Open 1600': 'K3',
        'Open 2000': 'K4',

        # TOSFED kisa sinif kodlari (sayisal)
        '2': 'Rally2',
        '3': 'Rally3',
        '4': 'Rally4',
        '5': 'Rally5',

        # TOSFED kisa kategori kodlari
        'K1': 'K1',
        'K2': 'K2',
        'K3': 'K3',
        'K4': 'K4',
        'H1': 'H1',
        'H2': 'H2',
        'N': 'N',
    }

    def normalize(self, raw_class: str) -> str:
        """
        Normalize a car class name.

        Args:
            raw_class: Raw class name from database

        Returns:
            Normalized class name

        Examples:
            >>> normalizer = CarClassNormalizer()
            >>> normalizer.normalize('R4')
            'Rally2'
            >>> normalizer.normalize('rally 2')
            'Rally2'
            >>> normalizer.normalize('S2000')
            'Rally2'
        """
        if not raw_class:
            logger.warning("Empty car class provided")
            return 'Unknown'

        # Clean whitespace
        cleaned = raw_class.strip()

        # Try exact match
        if cleaned in self.NORMALIZATION_MAP:
            normalized = self.NORMALIZATION_MAP[cleaned]
            logger.debug(f"Normalized '{raw_class}' → '{normalized}'")
            return normalized

        # Try case-insensitive match
        cleaned_lower = cleaned.lower()
        if cleaned_lower in self.NORMALIZATION_MAP:
            normalized = self.NORMALIZATION_MAP[cleaned_lower]
            logger.debug(f"Normalized '{raw_class}' → '{normalized}' (case-insensitive)")
            return normalized

        # Not found - return original with warning
        logger.warning(f"Unknown car class: '{raw_class}' - returning as-is")
        return cleaned


def main():
    """Test normalization."""
    normalizer = CarClassNormalizer()

    test_cases = [
        'R4',
        'S2000',
        'Rally 2',
        'rally2',
        'NR4',
        'Rally3',
        'R3T',
        'Kategori 3',
        'Unknown Class',
    ]

    print("Car Class Normalization Tests")
    print("=" * 50)

    for raw_class in test_cases:
        normalized = normalizer.normalize(raw_class)
        print(f"  '{raw_class:20s}' → '{normalized}'")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
