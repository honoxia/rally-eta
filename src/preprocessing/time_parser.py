"""Parse rally time strings to seconds"""
import re
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TimeParser:
    """Parse rally time strings to seconds"""

    FORMATS = [
        r'^(\d{1,2}):(\d{2})\.(\d{1,3})$',             # MM:SS.mmm
        r'^(\d{1,2}):(\d{2}):(\d{1,2})\.(\d{1,3})$',   # HH:MM:SS.mmm
        r'^(\d{1,2}):(\d{2}):(\d{2}):(\d{1,3})$',      # HH:MM:SS:d (TOSFED extended)
        r'^(\d{1,2}):(\d{2}):(\d{1,3})$',              # MM:SS:d (TOSFED format)
        r'^(\d{1,2}):(\d{2}):(\d{2})$',                # HH:MM:SS
        r'^(\d{1,2}):(\d{2})$',                        # MM:SS
    ]

    INVALID_MARKERS = ['DNF', 'DNS', 'DSQ', '—', '', 'N/A', 'RET']

    def parse(self, time_str: str) -> Optional[float]:
        """Parse time string to seconds"""
        if not time_str or not isinstance(time_str, str):
            return None

        time_str = time_str.strip().upper()

        # Check for invalid markers (exact match or substring for non-empty markers)
        if any(marker and marker in time_str for marker in self.INVALID_MARKERS):
            return None

        for pattern in self.FORMATS:
            match = re.match(pattern, time_str)
            if match:
                return self._convert_to_seconds(match)

        logger.warning(f"Could not parse: '{time_str}'")
        return None

    def _convert_to_seconds(self, match: re.Match) -> float:
        """Convert regex match to seconds"""
        groups = match.groups()

        if len(groups) == 4:
            # Could be HH:MM:SS.mmm or HH:MM:SS:d (TOSFED extended)
            if '.' in match.group(0):  # HH:MM:SS.mmm
                hours, minutes, seconds, ms = groups
                # Normalize milliseconds to 3 digits
                ms_normalized = int(ms) * (10 ** (3 - len(ms)))
                return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + ms_normalized / 1000
            else:  # HH:MM:SS:d (TOSFED extended: hours:minutes:seconds:deciseconds)
                hours, minutes, seconds, deciseconds = groups
                # Normalize deciseconds to 3 digits (convert to milliseconds)
                ms_normalized = int(deciseconds) * (10 ** (3 - len(deciseconds)))
                return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + ms_normalized / 1000

        elif len(groups) == 3:
            # Check if it has decimal point (MM:SS.mmm) or colon (MM:SS:d)
            if '.' in match.group(0):  # MM:SS.mmm
                minutes, seconds, ms = groups
                # Normalize milliseconds to 3 digits
                ms_normalized = int(ms) * (10 ** (3 - len(ms)))
                return int(minutes) * 60 + int(seconds) + ms_normalized / 1000
            elif match.group(0).count(':') == 2:
                # Could be HH:MM:SS or MM:SS:d (TOSFED format)
                # TOSFED uses MM:SS:d where d is 1 digit (deciseconds)
                # Rally stages are typically 1-30 minutes, rarely over 1 hour
                third_group = groups[2]
                first_group = int(groups[0])

                # If third group is 1 digit OR first group > 59, it's MM:SS:d
                if len(third_group) == 1 or first_group > 59:
                    # MM:SS:d (TOSFED format: minutes:seconds:deciseconds)
                    minutes, seconds, deciseconds = groups
                    # Normalize deciseconds to 3 digits (convert to milliseconds)
                    ms_normalized = int(deciseconds) * (10 ** (3 - len(deciseconds)))
                    return int(minutes) * 60 + int(seconds) + ms_normalized / 1000
                else:
                    # HH:MM:SS (for longer stages)
                    hours, minutes, seconds = groups
                    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
            else:  # HH:MM:SS
                hours, minutes, seconds = groups
                return int(hours) * 3600 + int(minutes) * 60 + int(seconds)

        elif len(groups) == 2:  # MM:SS
            minutes, seconds = groups
            return int(minutes) * 60 + int(seconds)

    def format_seconds(self, seconds: float) -> str:
        """Convert seconds back to MM:SS.SS format"""
        if seconds is None or seconds < 0:
            return "—"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:05.2f}"
        return f"{minutes}:{secs:05.2f}"
