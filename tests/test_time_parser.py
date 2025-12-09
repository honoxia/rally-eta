"""Tests for time parser"""
import pytest
from src.preprocessing.time_parser import TimeParser


def test_parse_mm_ss_mmm():
    """Test parsing MM:SS.mmm format"""
    parser = TimeParser()
    assert parser.parse("5:23.4") == 323.4
    assert parser.parse("12:34.567") == 754.567


def test_parse_hh_mm_ss_mmm():
    """Test parsing HH:MM:SS.mmm format"""
    parser = TimeParser()
    assert parser.parse("1:05:23.456") == 3923.456


def test_parse_mm_ss():
    """Test parsing MM:SS format"""
    parser = TimeParser()
    assert parser.parse("5:23") == 323.0


def test_parse_hh_mm_ss():
    """Test parsing HH:MM:SS format"""
    parser = TimeParser()
    assert parser.parse("1:05:23") == 3923.0


def test_parse_invalid():
    """Test parsing invalid time strings"""
    parser = TimeParser()
    assert parser.parse("DNF") is None
    assert parser.parse("DNS") is None
    assert parser.parse("DSQ") is None
    assert parser.parse("") is None
    assert parser.parse(None) is None
    assert parser.parse("invalid") is None


def test_format_seconds():
    """Test formatting seconds to time string"""
    parser = TimeParser()
    assert parser.format_seconds(323.4) == "5:23.40"
    assert parser.format_seconds(3923.456) == "1:05:23.46"
    assert parser.format_seconds(63.5) == "1:03.50"


def test_format_seconds_edge_cases():
    """Test edge cases for format_seconds"""
    parser = TimeParser()
    assert parser.format_seconds(None) == "—"
    assert parser.format_seconds(-1) == "—"
    assert parser.format_seconds(0) == "0:00.00"
