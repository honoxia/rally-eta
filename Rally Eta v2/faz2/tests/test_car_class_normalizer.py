"""
Unit tests for CarClassNormalizer
"""
import unittest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.car_class_normalizer import CarClassNormalizer


class TestCarClassNormalizer(unittest.TestCase):
    """Test car class normalization."""

    def setUp(self):
        self.normalizer = CarClassNormalizer()

    def test_rally2_variants(self):
        """Test Rally2 normalization."""
        rally2_variants = [
            'R4', 'VR4', 'NR4', 'S2000', 'S2000-Rally',
            'Rally2', 'Rally 2', 'rally2', 'Rally2 Kit'
        ]

        for variant in rally2_variants:
            with self.subTest(variant=variant):
                self.assertEqual(
                    self.normalizer.normalize(variant),
                    'Rally2',
                    f"Failed to normalize '{variant}' to Rally2"
                )

    def test_rally3_variants(self):
        """Test Rally3 normalization."""
        rally3_variants = ['Rally3', 'Rally 3', 'rally3']

        for variant in rally3_variants:
            with self.subTest(variant=variant):
                self.assertEqual(
                    self.normalizer.normalize(variant),
                    'Rally3'
                )

    def test_rally4_variants(self):
        """Test Rally4 normalization."""
        rally4_variants = ['Rally4', 'R2', 'R3', 'R3T', 'R3D', 'Grup A']

        for variant in rally4_variants:
            with self.subTest(variant=variant):
                self.assertEqual(
                    self.normalizer.normalize(variant),
                    'Rally4'
                )

    def test_tosfed_categories(self):
        """Test TOSFED category normalization."""
        categories = {
            'Kategori 1': 'K1',
            'Kategori 2': 'K2',
            'Kategori 3': 'K3',
            'Kategori 4': 'K4',
            'Open 1600': 'K3',
            'Open 2000': 'K4',
        }

        for raw, expected in categories.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    self.normalizer.normalize(raw),
                    expected
                )

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        self.assertEqual(self.normalizer.normalize('rally2'), 'Rally2')
        self.assertEqual(self.normalizer.normalize('RALLY2'), 'Rally2')
        self.assertEqual(self.normalizer.normalize('RaLLy2'), 'Rally2')

    def test_whitespace_handling(self):
        """Test whitespace trimming."""
        self.assertEqual(self.normalizer.normalize('  R4  '), 'Rally2')
        self.assertEqual(self.normalizer.normalize(' Rally2 '), 'Rally2')

    def test_unknown_class(self):
        """Test unknown class handling."""
        result = self.normalizer.normalize('CustomClass123')
        self.assertEqual(result, 'CustomClass123')  # Returns original

    def test_empty_class(self):
        """Test empty class handling."""
        result = self.normalizer.normalize('')
        self.assertEqual(result, 'Unknown')


if __name__ == '__main__':
    unittest.main()
