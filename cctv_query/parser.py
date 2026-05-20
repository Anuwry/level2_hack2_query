from __future__ import annotations

import re
from collections.abc import Iterable

from cctv_query.models import QuerySpec
from cctv_query.normalization import normalize_cctv_id, normalize_date, normalize_time, time_to_seconds


TIME_TOKEN = r"\d{1,2}:\d{1,2}(?::\d{1,2})?"
DATE_TOKEN = (
    r"\b(?:"
    r"\d{1,2}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{4}"
    r"|\d{4}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{1,2}"
    r"|\d{1,2}\s+\d{1,2}\s+\d{4}"
    r"|\d{4}\s+\d{1,2}\s+\d{1,2}"
    r")\b"
)

TYPE_ALIASES: tuple[tuple[str, str], ...] = (
    ("motorcycles", "Motorcycle"),
    ("motorcycle", "Motorcycle"),
    ("motorbikes", "Motorcycle"),
    ("motorbike", "Motorcycle"),
    ("มอเตอร์ไซค์", "Motorcycle"),
    ("มอเตอร์ไซต์", "Motorcycle"),
    ("จักรยานยนต์", "Motorcycle"),
    ("รถจักรยานยนต์", "Motorcycle"),
    ("trucks", "Truck"),
    ("truck", "Truck"),
    ("lorries", "Truck"),
    ("lorry", "Truck"),
    ("รถบรรทุก", "Truck"),
    ("รถสิบล้อ", "Truck"),
    ("buses", "Bus"),
    ("bus", "Bus"),
    ("รถบัส", "Bus"),
    ("รถเมล์", "Bus"),
    ("cars", "Car"),
    ("car", "Car"),
    ("private vehicles", "Car"),
    ("private vehicle", "Car"),
    ("private cars", "Car"),
    ("private car", "Car"),
    ("รถยนต์ส่วนบุคคล", "Car"),
    ("รถส่วนบุคคล", "Car"),
    ("ส่วนบุคคล", "Car"),
    ("รถยนต์", "Car"),
    ("รถเก๋ง", "Car"),
    ("เก๋ง", "Car"),
)

COLOR_ALIASES: tuple[tuple[str, str], ...] = (
    ("สีแดง", "Red"),
    ("แดง", "Red"),
    ("red", "Red"),
    ("สีขาว", "White"),
    ("ขาว", "White"),
    ("white", "White"),
    ("สีดำ", "Black"),
    ("ดำ", "Black"),
    ("black", "Black"),
    ("สีฟ้า", "Blue"),
    ("สีน้ำเงิน", "Blue"),
    ("ฟ้า", "Blue"),
    ("น้ำเงิน", "Blue"),
    ("blue", "Blue"),
    ("สีเขียว", "Green"),
    ("เขียว", "Green"),
    ("green", "Green"),
    ("สีเหลือง", "Yellow"),
    ("เหลือง", "Yellow"),
    ("yellow", "Yellow"),
    ("สีเทา", "Gray"),
    ("เทา", "Gray"),
    ("grey", "Gray"),
    ("gray", "Gray"),
    ("สีเงิน", "Silver"),
    ("เงิน", "Silver"),
    ("silver", "Silver"),
    ("สีส้ม", "Orange"),
    ("ส้ม", "Orange"),
    ("orange", "Orange"),
    ("สีชมพู", "Pink"),
    ("ชมพู", "Pink"),
    ("pink", "Pink"),
    ("สีม่วง", "Purple"),
    ("ม่วง", "Purple"),
    ("purple", "Purple"),
    ("สีน้ำตาล", "Brown"),
    ("น้ำตาล", "Brown"),
    ("brown", "Brown"),
    ("สีทอง", "Gold"),
    ("ทอง", "Gold"),
    ("gold", "Gold"),
    ("สีบรอนซ์", "Bronze"),
    ("บรอนซ์", "Bronze"),
    ("bronze", "Bronze"),
    ("สีเลือดหมู", "Maroon"),
    ("เลือดหมู", "Maroon"),
    ("maroon", "Maroon"),
)

VEHICLE_TYPE_WORDS = {"car", "cars", "bus", "buses", "truck", "trucks", "motorcycle", "motorcycles"}


def parse_question(
    question: str,
    known_brands: Iterable[str] | None = None,
    known_colors: Iterable[str] | None = None,
    known_dates: Iterable[str] | None = None,
) -> QuerySpec:
    text = question.strip()
    language = "th" if re.search(r"[\u0E00-\u0E7F]", text) else "en"
    date, date_out_of_range = _extract_date(text, known_dates)
    cctv_id = _extract_cctv_id(text)
    start_time, end_time = _extract_time_range(text)
    start_seconds = time_to_seconds(start_time) if start_time else None
    end_seconds = time_to_seconds(end_time) if end_time else None
    vehicle_type = _extract_alias(text, TYPE_ALIASES)
    colors = _extract_colors(text, known_colors)
    color = colors[0] if colors else None
    brand = _extract_brand(text, known_brands)
    wants_brand_color_breakdown = _wants_brand_color_breakdown(text)
    wants_route = _wants_route(text)
    wants_vehicle_list = _wants_vehicle_list(text)
    wants_distinct_vehicle_count = _wants_distinct_vehicle_count(text)
    out_of_range_fields = ("date",) if date_out_of_range else ()

    return QuerySpec(
        raw_question=question,
        language=language,
        date=date,
        cctv_id=cctv_id,
        start_time=start_time,
        end_time=end_time,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        brand=brand,
        color=color,
        colors=colors,
        vehicle_type=vehicle_type,
        wants_brand_color_breakdown=wants_brand_color_breakdown,
        wants_route=wants_route,
        wants_vehicle_list=wants_vehicle_list,
        wants_distinct_vehicle_count=wants_distinct_vehicle_count,
        out_of_range_fields=out_of_range_fields,
    )


def _extract_date(text: str, known_dates: Iterable[str] | None = None) -> tuple[str | None, bool]:
    match = re.search(DATE_TOKEN, text)
    if match:
        return normalize_date(_clean_date_text(match.group(0))), False

    day = _extract_day_only_date(text)
    if day is None:
        return None, False
    resolved_date = _resolve_day_from_known_dates(day, known_dates)
    if resolved_date:
        return resolved_date, False
    return None, _day_is_out_of_known_dates(day, known_dates)


def _extract_day_only_date(text: str) -> int | None:
    patterns = (
        r"วันที่\s*(\d{1,2})(?!\s*[-/]\s*\d)",
        r"\b(?:date|day)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        r"\bon\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            day = int(match.group(1))
            if 1 <= day <= 31:
                return day
    return None


def _clean_date_text(text: str) -> str:
    return re.sub(r"\s*([-/])\s*", r"\1", text.strip())


def _resolve_day_from_known_dates(day: int, known_dates: Iterable[str] | None) -> str | None:
    if not known_dates:
        return None

    normalized_dates = sorted({normalize_date(date) for date in known_dates})
    matches = [date for date in normalized_dates if int(date.split("-", maxsplit=1)[0]) == day]
    if len(matches) == 1:
        return matches[0]
    return None


def _day_is_out_of_known_dates(day: int, known_dates: Iterable[str] | None) -> bool:
    if not known_dates:
        return False
    normalized_dates = sorted({normalize_date(date) for date in known_dates})
    return not any(int(date.split("-", maxsplit=1)[0]) == day for date in normalized_dates)


def _extract_cctv_id(text: str) -> str | None:
    direct = re.search(r"\bCCTV\s*[0oO]*(\d{1,2})\b", text, flags=re.IGNORECASE)
    if direct:
        return normalize_cctv_id(direct.group(1))

    thai_camera = re.search(
        r"กล้อง\s*(?:(?:หมายเลข|ตัวที่|ตัว|ที่)\s*)?0*(\d{1,2})\b",
        text,
        flags=re.IGNORECASE,
    )
    if thai_camera:
        return normalize_cctv_id(thai_camera.group(1))
    return None


def _extract_time_range(text: str) -> tuple[str | None, str | None]:
    matches = re.findall(TIME_TOKEN, text)
    if len(matches) < 2:
        return None, None
    return normalize_time(matches[0]), normalize_time(matches[1])


def _extract_alias(text: str, aliases: Iterable[tuple[str, str]]) -> str | None:
    normalized_text = text.casefold()
    for alias, canonical in sorted(aliases, key=lambda item: len(item[0]), reverse=True):
        alias_folded = alias.casefold()
        if _contains_term(normalized_text, alias_folded):
            return canonical
    return None


def _extract_known_phrase(text: str, known_values: Iterable[str] | None) -> str | None:
    if not known_values:
        return None

    normalized_text = text.casefold()
    for value in sorted({item.strip() for item in known_values if item.strip()}, key=len, reverse=True):
        if _contains_term(normalized_text, value.casefold()):
            return value
    return None


def _extract_colors(text: str, known_colors: Iterable[str] | None) -> tuple[str, ...]:
    colors: list[str] = []
    for color in _extract_known_phrases(text, known_colors):
        if color not in colors:
            colors.append(color)
    if colors:
        return tuple(colors)

    alias_color = _extract_alias(text, COLOR_ALIASES)
    if alias_color and alias_color not in colors:
        colors.append(alias_color)
    return tuple(colors)


def _extract_known_phrases(text: str, known_values: Iterable[str] | None) -> list[str]:
    if not known_values:
        return []

    normalized_text = text.casefold()
    candidates = sorted({item.strip() for item in known_values if item.strip()}, key=len, reverse=True)
    matches: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []

    for value in candidates:
        value_folded = value.casefold()
        for start, end in _term_spans(normalized_text, value_folded):
            if any(not (end <= used_start or start >= used_end) for used_start, used_end in occupied):
                continue
            matches.append((start, end, value))
            occupied.append((start, end))

    return [value for _, _, value in sorted(matches, key=lambda item: item[0])]


def _extract_brand(text: str, known_brands: Iterable[str] | None) -> str | None:
    brands = [
        brand
        for brand in (known_brands or [])
        if brand.strip() and brand.strip().casefold() not in VEHICLE_TYPE_WORDS
    ]
    exact_match = _extract_known_phrase(text, brands)
    if exact_match:
        return exact_match
    return _extract_brand_alias(text, brands)


def _extract_brand_alias(text: str, brands: Iterable[str]) -> str | None:
    normalized_text = text.casefold()
    alias_matches: list[tuple[int, str]] = []

    for brand in brands:
        for alias in _brand_aliases(brand):
            if _contains_term(normalized_text, alias.casefold()):
                alias_matches.append((len(alias), brand))

    matched_brands = {brand for _, brand in alias_matches}
    if len(matched_brands) != 1:
        return None
    return max(alias_matches, key=lambda item: item[0])[1]


def _brand_aliases(brand: str) -> set[str]:
    aliases = {brand.replace("-", " "), brand.replace(" ", "-")}
    for token in re.split(r"[\s\-]+", brand):
        token = token.strip()
        if len(token) >= 3 and token.casefold() not in VEHICLE_TYPE_WORDS:
            aliases.add(token)
    return aliases


def _contains_term(normalized_text: str, normalized_term: str) -> bool:
    return bool(_term_spans(normalized_text, normalized_term))


def _term_spans(normalized_text: str, normalized_term: str) -> list[tuple[int, int]]:
    if re.fullmatch(r"[a-z0-9][a-z0-9\-\s]*", normalized_term):
        return [
            (match.start(), match.end())
            for match in re.finditer(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", normalized_text)
        ]
    return [(match.start(), match.end()) for match in re.finditer(re.escape(normalized_term), normalized_text)]


def _wants_brand_color_breakdown(text: str) -> bool:
    normalized_text = text.casefold()
    return (
        "ยี่ห้อ" in normalized_text
        or "brand" in normalized_text
        or bool(re.search(r"สี.*อะไร|อะไร.*สี", normalized_text))
        or "color?" in normalized_text
        or "colour?" in normalized_text
    )


def _wants_route(text: str) -> bool:
    normalized_text = text.casefold()
    return any(
        term in normalized_text
        for term in (
            "route",
            "path",
            "direction",
            "travel",
            "เส้นทาง",
            "เดินทาง",
            "ไปทางไหน",
            "ผ่านกล้องไหน",
            "ผ่านทางไหน",
        )
    )


def _wants_vehicle_list(text: str) -> bool:
    normalized_text = text.casefold()
    return any(
        term in normalized_text
        for term in (
            "คันไหน",
            "คันใด",
            "รถอะไรบ้าง",
            "มีรถอะไร",
            "รายการรถ",
            "รายชื่อรถ",
            "which vehicles",
            "which cars",
            "list vehicles",
            "list cars",
            "show vehicles",
            "show cars",
        )
    )


def _wants_distinct_vehicle_count(text: str) -> bool:
    normalized_text = text.casefold()
    return any(
        term in normalized_text
        for term in (
            "\u0e44\u0e21\u0e48\u0e0b\u0e49\u0e33",
            "\u0e44\u0e21\u0e48\u0e0b\u0e49\u0e33\u0e01\u0e31\u0e19",
            "distinct vehicles",
            "distinct cars",
            "unique vehicles",
            "unique cars",
            "dedupe",
            "deduplicated",
        )
    )
