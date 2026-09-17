"""Manual stage calculator for commissioner-driven fallback estimates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


METHOD_GAP_WARNING_SECONDS = 5.0
TIME_FORMAT_EXAMPLE = "01:10:800"

# Aykiri referans elemesi: lastik/ariza yasanan bir referans etap, 6 etaplik
# ortalamayi tek basina bozuyor. Medyan + MAD ile sapan etaplari eliyoruz.
OUTLIER_MIN_REFERENCES = 4  # bu sayinin altinda eleme yapilmaz
OUTLIER_MIN_KEPT = 3  # elemeden sonra en az bu kadar referans kalmali
OUTLIER_MAD_MULTIPLIER = 3.0
OUTLIER_RELATIVE_FLOOR = 0.10  # medyanin %10'u icindeki sapmalar hic elenmez
_MAD_NORMAL_SCALE = 1.4826


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


def build_manual_payload_from_rally(
    rally_data: Mapping[str, Any],
    driver_name: str,
    target_stage_number: int,
    max_reference_stages: int = 6,
) -> dict[str, Any]:
    """Build manual-calculator inputs from scraped rally results.

    Raw class names are matched exactly; no class normalization or general-best
    fallback is applied. Only stages with a valid length, same-class best time,
    and a valid time for the selected driver are used as references.
    """
    stages = sorted(
        rally_data.get("stages") or [],
        key=lambda stage: int(stage.get("stage_number") or 0),
    )
    target_stage = next(
        (
            stage
            for stage in stages
            if int(stage.get("stage_number") or 0) == int(target_stage_number)
        ),
        None,
    )
    if not target_stage:
        raise ValueError(f"Hedef etap bulunamadı: SS{target_stage_number}")

    class_name = _find_driver_raw_class(stages, driver_name, int(target_stage_number))
    if not class_name:
        raise ValueError(f"{driver_name} için ham sınıf bilgisi bulunamadı.")

    target_km = _coerce_optional_km(target_stage.get("stage_length_km"))
    if target_km is None:
        raise ValueError(
            f"SS{target_stage_number} etap uzunluğu URL verisinde bulunamadı. "
            "Hedef etap kilometresini manuel girin."
        )

    target_best = _find_same_class_best_time(target_stage, class_name)
    if not target_best:
        raise ValueError(
            f"SS{target_stage_number} için {class_name} sınıfında geçerli best derece henüz yok. "
            "Sonuç sayfasında sınıftan en az bir finiş olmalı."
        )

    references: list[dict[str, Any]] = []
    skipped_stages: list[str] = []
    for stage in stages:
        stage_number = int(stage.get("stage_number") or 0)
        if stage_number >= int(target_stage_number):
            continue

        stage_km = _coerce_optional_km(stage.get("stage_length_km"))
        best_time = _find_same_class_best_time(stage, class_name)
        driver_time = _find_driver_time(stage, driver_name)
        label = _stage_label(stage)
        if stage_km is None or not best_time or not driver_time:
            skipped_stages.append(label)
            continue

        references.append(
            {
                "label": label,
                "km": stage_km,
                "best_time": best_time,
                "driver_time": driver_time,
            }
        )

    references = references[-max(1, int(max_reference_stages)) :]
    if not references:
        raise ValueError(
            f"{driver_name} için SS{target_stage_number} öncesinde hesapta kullanılabilecek "
            f"tam {class_name} sınıfı referansı bulunamadı."
        )

    return {
        "class_name": class_name,
        "driver_name": driver_name,
        "rally_name": str(rally_data.get("rally_name") or ""),
        "references": references,
        "target": {
            "label": _stage_label(target_stage),
            "km": target_km,
            "best_time": target_best,
        },
        "skipped_stages": skipped_stages,
    }


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

    reference_details, outlier_notes = _drop_reference_outliers(reference_details)
    ignored_references.extend(outlier_notes)

    used_stage_count = len(reference_details)
    average_diff_per_km = sum(item.diff_per_km for item in reference_details) / used_stage_count
    average_ratio = sum(item.ratio for item in reference_details) / used_stage_count
    target_diff_seconds = average_diff_per_km * target_km
    km_based_prediction_seconds = target_best_seconds + target_diff_seconds
    percentage_prediction_seconds = target_best_seconds * average_ratio
    methods_gap_seconds = abs(km_based_prediction_seconds - percentage_prediction_seconds)

    warnings: list[str] = []
    if outlier_notes:
        warnings.append(
            f"{len(outlier_notes)} referans etap, pilotun kendi normalinden belirgin saptığı için "
            "hesaba katılmadı (olası lastik/arıza). Ayrıntı için atlanan satırlara bakın."
        )
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


def _drop_reference_outliers(
    reference_details: Sequence[ManualReferenceStageResult],
) -> tuple[list[ManualReferenceStageResult], list[str]]:
    """Drop reference stages where the driver deviates from their own norm.

    Uses the class-best ratio, which is comparable across stage lengths. The
    spread is measured with median absolute deviation so a single bad stage
    cannot widen the threshold that is supposed to catch it. A relative floor
    keeps consistent drivers from having ordinary stages eliminated, and at
    least OUTLIER_MIN_KEPT references always survive.
    """
    details = list(reference_details)
    if len(details) < OUTLIER_MIN_REFERENCES:
        return details, []

    ratios = [item.ratio for item in details]
    median_ratio = _median(ratios)
    scaled_mad = _median([abs(ratio - median_ratio) for ratio in ratios]) * _MAD_NORMAL_SCALE
    threshold = max(OUTLIER_MAD_MULTIPLIER * scaled_mad, OUTLIER_RELATIVE_FLOOR * median_ratio)

    flagged = [item for item in details if abs(item.ratio - median_ratio) > threshold]
    if not flagged:
        return details, []

    # En cok sapandan basla, ama en az OUTLIER_MIN_KEPT referans birak.
    flagged.sort(key=lambda item: abs(item.ratio - median_ratio), reverse=True)
    droppable = min(len(flagged), len(details) - OUTLIER_MIN_KEPT)
    if droppable <= 0:
        return details, []

    dropped = set(id(item) for item in flagged[:droppable])
    kept = [item for item in details if id(item) not in dropped]
    notes = [
        f"{item.label}: pilotun referans normalinden sapıyor "
        f"(oran {item.ratio:.3f}, medyan {median_ratio:.3f}); hesaba katılmadı."
        for item in details
        if id(item) in dropped
    ]
    return kept, notes


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _has_reference_input(km: float | None, best_input: str, driver_input: str) -> bool:
    return bool((km and km > 0) or best_input or driver_input)


def _find_driver_raw_class(
    stages: Sequence[Mapping[str, Any]],
    driver_name: str,
    target_stage_number: int,
) -> str:
    eligible = [
        stage
        for stage in stages
        if int(stage.get("stage_number") or 0) <= target_stage_number
    ]
    for stage in reversed(eligible):
        for result in stage.get("results") or []:
            if str(result.get("driver_name") or "").strip() != driver_name.strip():
                continue
            class_name = str(result.get("car_class") or "").strip()
            if class_name:
                return class_name
    return ""


def _find_same_class_best_time(stage: Mapping[str, Any], class_name: str) -> str:
    candidates: list[tuple[float, str]] = []
    for result in stage.get("results") or []:
        if str(result.get("car_class") or "").strip() != class_name:
            continue
        time_input = str(result.get("time_str") or "").strip()
        try:
            seconds = parse_manual_time_input(time_input)
        except ValueError:
            continue
        candidates.append((seconds, time_input))
    return min(candidates, default=(0.0, ""), key=lambda item: item[0])[1]


def _find_driver_time(stage: Mapping[str, Any], driver_name: str) -> str:
    for result in stage.get("results") or []:
        if str(result.get("driver_name") or "").strip() != driver_name.strip():
            continue
        time_input = str(result.get("time_str") or "").strip()
        try:
            parse_manual_time_input(time_input)
        except ValueError:
            return ""
        return time_input
    return ""


def _stage_label(stage: Mapping[str, Any]) -> str:
    stage_number = int(stage.get("stage_number") or 0)
    stage_name = str(stage.get("stage_name") or "").strip()
    return f"SS{stage_number}: {stage_name}" if stage_name else f"SS{stage_number}"


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
