"""Manual stage calculator for commissioner-driven fallback estimates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


METHOD_GAP_WARNING_SECONDS = 5.0
TIME_FORMAT_EXAMPLE = "01:10:800"


@dataclass(frozen=True)
class ManualReferenceStageResult:
    label: str
    km: float
    best_time_input: str
    best_time_seconds: float
    driver_time_input: str
    driver_time_seconds: float
    diff_seconds: float
    diff_per_km: float
    ratio: float


@dataclass(frozen=True)
class ManualCalculationResult:
    class_name: str
    used_stage_count: int
    ignored_stage_count: int
    ignored_references: tuple[str, ...]
    reference_details: tuple[ManualReferenceStageResult, ...]
    target_km: float
    target_best_input: str
    target_best_seconds: float
    average_diff_per_km: float
    average_ratio: float
    target_diff_seconds: float
    km_based_prediction_seconds: float
    percentage_prediction_seconds: float
    methods_gap_seconds: float
    warnings: tuple[str, ...]


def parse_manual_time_input(value: str) -> float:
    """Parse manual rally time input into total seconds.

    Supported examples:
    - 01:10:800
    - 01:30:3
    - 10:37:900
    - 04:18:300
    - 04:18.300
    - 1:04:02  (hour-based fallback)
    """
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("Zaman boş bırakılamaz.")

    normalized = raw_value.replace(",", ".")

    if ":" not in normalized:
        return _parse_positive_seconds(normalized, raw_value)

    parts = normalized.split(":")
    if len(parts) == 2:
        minutes = _parse_non_negative_int(parts[0], raw_value)
        seconds = _parse_positive_float(parts[1], raw_value)
        if seconds >= 60:
            raise ValueError(f"Saniye alanı 60'tan küçük olmalı: {raw_value}")
        return _ensure_positive(minutes * 60 + seconds, raw_value)

    if len(parts) != 3:
        raise ValueError(f"Geçersiz zaman formatı: {raw_value}. Örnek: {TIME_FORMAT_EXAMPLE}")

    first = _parse_non_negative_int(parts[0], raw_value)
    second = _parse_non_negative_int(parts[1], raw_value)
    if second >= 60:
        raise ValueError(f"Orta bölüm 60'tan küçük olmalı: {raw_value}")

    third_raw = parts[2].strip()
    if not third_raw.isdigit():
        raise ValueError(f"Geçersiz zaman formatı: {raw_value}. Örnek: {TIME_FORMAT_EXAMPLE}")

    if len(third_raw) in {1, 3}:
        fraction = int(third_raw) / (10 if len(third_raw) == 1 else 1000)
        total_seconds = first * 60 + second + fraction
        return _ensure_positive(total_seconds, raw_value)

    if len(third_raw) == 2:
        seconds = int(third_raw)
        if seconds >= 60:
            raise ValueError(f"Son bölüm 60'tan küçük olmalı: {raw_value}")
        total_seconds = first * 3600 + second * 60 + seconds
        return _ensure_positive(total_seconds, raw_value)

    raise ValueError(f"Geçersiz zaman formatı: {raw_value}. Örnek: {TIME_FORMAT_EXAMPLE}")


def format_manual_time(seconds: float) -> str:
    """Format seconds into MM:SS:ms for manual calculator output."""
    sign = "-" if seconds < 0 else ""
    remaining = abs(float(seconds))

    total_minutes = int(remaining // 60)
    whole_seconds = int(remaining % 60)
    milliseconds = int(round((remaining - int(remaining)) * 1000))

    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0
    if whole_seconds == 60:
        total_minutes += 1
        whole_seconds = 0

    return f"{sign}{total_minutes:02d}:{whole_seconds:02d}:{milliseconds:03d}"


def calculate_manual_stage_estimate(
    reference_rows: Sequence[Mapping[str, object]],
    target_row: Mapping[str, object],
    class_name: str = "",
) -> ManualCalculationResult:
    """Calculate both km-based and ratio-based manual predictions."""
    target_km = _coerce_positive_km(target_row.get("km"), "Hedef Etap Km")
    target_best_input = str(target_row.get("best_time") or "").strip()
    if not target_best_input:
        raise ValueError("Hedef Etap Best Derece zorunlu.")

    try:
        target_best_seconds = parse_manual_time_input(target_best_input)
    except ValueError as exc:
        raise ValueError(f"Hedef Etap Best Derece hatalı: {exc}") from exc

    reference_details: list[ManualReferenceStageResult] = []
    ignored_references: list[str] = []

    for index, row in enumerate(reference_rows, start=1):
        label = str(row.get("label") or f"Etap {index}")
        km = _coerce_optional_km(row.get("km"))
        best_input = str(row.get("best_time") or "").strip()
        driver_input = str(row.get("driver_time") or "").strip()

        if not _has_reference_input(km, best_input, driver_input):
            continue

        if not km or not best_input or not driver_input:
            ignored_references.append(f"{label}: km, best derece ve pilot süresi birlikte girilmediği için kullanılmadı.")
            continue

        try:
            best_seconds = parse_manual_time_input(best_input)
        except ValueError:
            ignored_references.append(f"{label}: best derece formatı geçersiz olduğu için kullanılmadı.")
            continue

        try:
            driver_seconds = parse_manual_time_input(driver_input)
        except ValueError:
            ignored_references.append(f"{label}: pilot süresi formatı geçersiz olduğu için kullanılmadı.")
            continue

        diff_seconds = driver_seconds - best_seconds
        reference_details.append(
            ManualReferenceStageResult(
                label=label,
                km=km,
                best_time_input=best_input,
                best_time_seconds=best_seconds,
                driver_time_input=driver_input,
                driver_time_seconds=driver_seconds,
                diff_seconds=diff_seconds,
                diff_per_km=diff_seconds / km,
                ratio=driver_seconds / best_seconds,
            )
        )

    if not reference_details:
        raise ValueError("Hesap için en az 1 tam referans etap gerekli.")

    used_stage_count = len(reference_details)
    average_diff_per_km = sum(item.diff_per_km for item in reference_details) / used_stage_count
    average_ratio = sum(item.ratio for item in reference_details) / used_stage_count
    target_diff_seconds = average_diff_per_km * target_km
    km_based_prediction_seconds = target_best_seconds + target_diff_seconds
    percentage_prediction_seconds = target_best_seconds * average_ratio
    methods_gap_seconds = abs(km_based_prediction_seconds - percentage_prediction_seconds)

    warnings: list[str] = []
    if used_stage_count == 1:
        warnings.append("Sadece 1 etap kullanıldı; sonuç düşük güven seviyesinde değerlendirilmeli.")
    if methods_gap_seconds >= METHOD_GAP_WARNING_SECONDS:
        warnings.append("İki yöntem arasında belirgin fark var; referans etap girişlerini tekrar kontrol edin.")

    return ManualCalculationResult(
        class_name=str(class_name or "").strip(),
        used_stage_count=used_stage_count,
        ignored_stage_count=len(ignored_references),
        ignored_references=tuple(ignored_references),
        reference_details=tuple(reference_details),
        target_km=target_km,
        target_best_input=target_best_input,
        target_best_seconds=target_best_seconds,
        average_diff_per_km=average_diff_per_km,
        average_ratio=average_ratio,
        target_diff_seconds=target_diff_seconds,
        km_based_prediction_seconds=km_based_prediction_seconds,
        percentage_prediction_seconds=percentage_prediction_seconds,
        methods_gap_seconds=methods_gap_seconds,
        warnings=tuple(warnings),
    )


def _has_reference_input(km: float | None, best_input: str, driver_input: str) -> bool:
    return bool((km and km > 0) or best_input or driver_input)


def _coerce_optional_km(value: object) -> float | None:
    if value in (None, "", 0, 0.0):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_positive_km(value: object, label: str) -> float:
    parsed = _coerce_optional_km(value)
    if parsed is None:
        raise ValueError(f"{label} zorunlu ve 0'dan büyük olmalı.")
    return parsed


def _parse_positive_seconds(value: str, raw_value: str) -> float:
    try:
        return _ensure_positive(float(value), raw_value)
    except ValueError as exc:
        raise ValueError(f"Geçersiz zaman formatı: {raw_value}. Örnek: {TIME_FORMAT_EXAMPLE}") from exc


def _parse_positive_float(value: str, raw_value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"Geçersiz zaman formatı: {raw_value}. Örnek: {TIME_FORMAT_EXAMPLE}") from exc
    return _ensure_positive(parsed, raw_value)


def _parse_non_negative_int(value: str, raw_value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Geçersiz zaman formatı: {raw_value}. Örnek: {TIME_FORMAT_EXAMPLE}") from exc
    if parsed < 0:
        raise ValueError(f"Geçersiz zaman formatı: {raw_value}. Örnek: {TIME_FORMAT_EXAMPLE}")
    return parsed


def _ensure_positive(value: float, raw_value: str) -> float:
    if value <= 0:
        raise ValueError(f"Zaman 0'dan büyük olmalı: {raw_value}")
    return value

