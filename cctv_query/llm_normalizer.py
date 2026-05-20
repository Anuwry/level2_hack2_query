from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cctv_query.normalization import normalize_cctv_id, normalize_date, normalize_time


DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_LLM_MODEL = "Qwen/Qwen3.5-4B"
DEFAULT_LLM_TIMEOUT_SECONDS = 8.0
TOOL_NAME = "normalize_cctv_query"
VEHICLE_TYPES = ("Car", "Motorcycle", "Bus", "Truck")

JsonTransport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


class LLMHTTPError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"LLM HTTP {status_code}: {message}")


@dataclass(frozen=True)
class LLMNormalizationResult:
    original_question: str
    normalized_question: str
    enabled: bool
    used: bool
    model: str
    base_url: str
    mode: str
    error: str | None = None

    @property
    def changed(self) -> bool:
        return self.original_question.strip() != self.normalized_question.strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "used": self.used,
            "changed": self.changed,
            "model": self.model,
            "base_url": self.base_url,
            "mode": self.mode,
            "original_question": self.original_question,
            "normalized_question": self.normalized_question,
            "error": self.error,
        }


def normalize_question_if_enabled(
    question: str,
    *,
    known_brands: list[str] | tuple[str, ...] | None = None,
    known_colors: list[str] | tuple[str, ...] | None = None,
    known_dates: list[str] | tuple[str, ...] | None = None,
    enabled: bool | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout_seconds: float | None = None,
    mode: str | None = None,
    transport: JsonTransport | None = None,
) -> LLMNormalizationResult:
    text = question.strip()
    configured_enabled = _env_bool("CCTV_LLM_ENABLED", default=False) if enabled is None else enabled
    configured_base_url = base_url or os.getenv("CCTV_LLM_BASE_URL") or DEFAULT_LLM_BASE_URL
    configured_model = model or os.getenv("CCTV_LLM_MODEL") or DEFAULT_LLM_MODEL
    configured_mode = _normalize_mode(mode or os.getenv("CCTV_LLM_MODE") or "auto")
    configured_timeout = _timeout_from_env(timeout_seconds)

    if not configured_enabled:
        return LLMNormalizationResult(
            original_question=text,
            normalized_question=text,
            enabled=False,
            used=False,
            model=configured_model,
            base_url=configured_base_url,
            mode=configured_mode,
        )

    headers = _headers(api_key if api_key is not None else os.getenv("CCTV_LLM_API_KEY"))
    transport_fn = transport or _post_json
    attempts = _attempt_modes(configured_mode)
    errors: list[str] = []

    for attempt_mode in attempts:
        body = build_chat_completion_request(
            text,
            known_brands=known_brands,
            known_colors=known_colors,
            known_dates=known_dates,
            model=configured_model,
            mode=attempt_mode,
        )
        try:
            response = transport_fn(
                chat_completions_url(configured_base_url),
                body,
                headers,
                configured_timeout,
            )
        except LLMHTTPError as exc:
            errors.append(str(exc))
            if attempt_mode == "tools" and configured_mode == "auto" and exc.status_code in {400, 404, 405, 422}:
                continue
            break
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            errors.append(str(exc))
            break

        try:
            payload = extract_normalization_payload(response)
            normalized = canonical_question_from_payload(
                text,
                payload,
                known_brands=known_brands,
                known_colors=known_colors,
                known_dates=known_dates,
            )
        except ValueError as exc:
            errors.append(str(exc))
            if attempt_mode == "tools" and configured_mode == "auto":
                continue
            break

        return LLMNormalizationResult(
            original_question=text,
            normalized_question=normalized,
            enabled=True,
            used=True,
            model=configured_model,
            base_url=configured_base_url,
            mode=attempt_mode,
        )

    return LLMNormalizationResult(
        original_question=text,
        normalized_question=text,
        enabled=True,
        used=False,
        model=configured_model,
        base_url=configured_base_url,
        mode=configured_mode,
        error="; ".join(errors) if errors else "LLM did not return a usable normalization.",
    )


def build_chat_completion_request(
    question: str,
    *,
    known_brands: list[str] | tuple[str, ...] | None,
    known_colors: list[str] | tuple[str, ...] | None,
    known_dates: list[str] | tuple[str, ...] | None,
    model: str,
    mode: str,
) -> dict[str, Any]:
    context = {
        "question": question,
        "known_brands": _clean_list(known_brands),
        "known_colors": _clean_list(known_colors),
        "known_dates": _clean_known_dates(known_dates),
        "vehicle_types": list(VEHICLE_TYPES),
    }
    request: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(mode)},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 700,
        "stream": False,
    }

    if mode == "tools":
        request["tools"] = [_tool_schema(context["known_brands"], context["known_colors"], context["known_dates"])]
        request["tool_choice"] = {"type": "function", "function": {"name": TOOL_NAME}}
    return request


def chat_completions_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def extract_normalization_payload(response: dict[str, Any]) -> dict[str, Any]:
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("LLM response does not contain choices[0].message.") from exc

    payload = _payload_from_tool_calls(message)
    if payload is not None:
        return payload

    function_call = message.get("function_call")
    if isinstance(function_call, dict) and function_call.get("name") == TOOL_NAME:
        return _parse_json_document(function_call.get("arguments"))

    content = _message_content_to_text(message.get("content"))
    if content:
        return _parse_json_document(content)

    raise ValueError("LLM response did not contain a tool call or JSON content.")


def canonical_question_from_payload(
    original_question: str,
    payload: dict[str, Any],
    *,
    known_brands: list[str] | tuple[str, ...] | None = None,
    known_colors: list[str] | tuple[str, ...] | None = None,
    known_dates: list[str] | tuple[str, ...] | None = None,
) -> str:
    explicit_question = _string_or_none(payload.get("normalized_question"))
    if explicit_question:
        return explicit_question

    parts: list[str] = []
    date = _canonical_date(payload.get("date"), known_dates)
    cctv_id = _canonical_cctv_id(payload.get("cctv_id"))
    start_time = _canonical_time(payload.get("start_time"))
    end_time = _canonical_time(payload.get("end_time"))
    brand = _canonical_known(payload.get("brand"), known_brands)
    colors = _canonical_colors(payload, known_colors)
    vehicle_type = _canonical_vehicle_type(payload.get("vehicle_type"))

    if date:
        parts.append(f"date {date}")
    if cctv_id:
        parts.append(cctv_id)
    if start_time and end_time:
        parts.append(f"from {start_time} to {end_time}")
    if brand:
        parts.append(f"brand {brand}")
    if colors:
        parts.append(f"color {' and '.join(colors)}")
    if vehicle_type:
        parts.append(f"type {vehicle_type}")
    if _truthy(payload.get("wants_brand_color_breakdown")):
        parts.append("brand and color")
    if _truthy(payload.get("wants_route")):
        parts.append("route")
    if _truthy(payload.get("wants_vehicle_list")):
        parts.append("which vehicles")
    if _truthy(payload.get("wants_distinct_vehicle_count")):
        parts.append("unique vehicles")

    return " ".join(parts) if parts else original_question.strip()


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout_seconds: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            content = response.read().decode("utf-8")
    except HTTPError as exc:
        error_content = exc.read().decode("utf-8", errors="replace")
        raise LLMHTTPError(exc.code, error_content or str(exc.reason)) from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object.")
    return parsed


def _payload_from_tool_calls(message: dict[str, Any]) -> dict[str, Any] | None:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return None

    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function")
        if not isinstance(function, dict) or function.get("name") != TOOL_NAME:
            continue
        return _parse_json_document(function.get("arguments"))
    return None


def _parse_json_document(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        raise ValueError("JSON payload is empty.")

    text = str(value).strip()
    if not text:
        raise ValueError("JSON payload is empty.")
    text = _strip_markdown_fence(text)
    text = _extract_json_object_text(text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM normalization payload was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM normalization payload must be a JSON object.")
    return parsed


def _strip_markdown_fence(text: str) -> str:
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else text


def _extract_json_object_text(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks).strip()
    return ""


def _tool_schema(known_brands: list[str], known_colors: list[str], known_dates: list[str]) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "normalized_question": {
            "type": "string",
            "description": "Optional canonical plain text query. Omit if structured fields are enough.",
        },
        "date": {"type": "string", "description": "Date in DD-MM-YYYY when known."},
        "cctv_id": {"type": "string", "description": "Camera id, e.g. CCTV01."},
        "start_time": {"type": "string", "description": "Start time in HH:MM:SS."},
        "end_time": {"type": "string", "description": "End time in HH:MM:SS."},
        "brand": {"type": "string", "description": "Vehicle brand from known_brands when possible."},
        "colors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Exact vehicle colors. Multiple colors mean OR.",
        },
        "vehicle_type": {"type": "string", "enum": list(VEHICLE_TYPES)},
        "wants_brand_color_breakdown": {"type": "boolean"},
        "wants_route": {"type": "boolean"},
        "wants_vehicle_list": {"type": "boolean"},
        "wants_distinct_vehicle_count": {"type": "boolean"},
    }
    if known_brands:
        properties["brand"]["enum"] = known_brands
    if known_colors:
        properties["colors"]["items"]["enum"] = known_colors
    if known_dates:
        properties["date"]["enum"] = known_dates

    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Normalize a Thai or English CCTV log question into fields that a CSV query engine can parse.",
            "parameters": {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
            },
        },
    }


def _system_prompt(mode: str) -> str:
    base_rules = (
        "You normalize user questions for a CCTV CSV query engine. "
        "Do not answer the data question. Extract only filters and intent. "
        "Use known CSV values exactly when they are unambiguous. "
        "Do not invent brands, colors, dates, cameras, or vehicle types. "
        "Map informal camera numbers such as 'camera one' to CCTV01. "
        "Map private/personal vehicle to Car. "
        "Map Benz to Mercedes-Benz only if that brand is present in known_brands. "
        "Use exact colors: Red is not Red-White, and Green is not Metallic Green. "
        "For multiple colors, keep every requested color as an OR list. "
        "Set wants_vehicle_list for questions asking which vehicles or list of vehicles. "
        "Set wants_distinct_vehicle_count for questions asking for non-duplicate or unique vehicle counts. "
        "Set wants_route for route/path/travel-direction questions."
    )
    if mode == "tools":
        return base_rules + " Call the normalize_cctv_query tool exactly once."
    return (
        base_rules
        + " Return only a JSON object with fields: normalized_question, date, cctv_id, "
        "start_time, end_time, brand, colors, vehicle_type, wants_brand_color_breakdown, "
        "wants_route, wants_vehicle_list, wants_distinct_vehicle_count."
    )


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _attempt_modes(mode: str) -> tuple[str, ...]:
    if mode == "tools":
        return ("tools",)
    if mode == "json":
        return ("json",)
    return ("tools", "json")


def _normalize_mode(mode: str) -> str:
    normalized = mode.strip().casefold()
    if normalized in {"tools", "tool"}:
        return "tools"
    if normalized in {"json", "content"}:
        return "json"
    return "auto"


def _timeout_from_env(timeout_seconds: float | None) -> float:
    if timeout_seconds is not None:
        return float(timeout_seconds)
    value = os.getenv("CCTV_LLM_TIMEOUT_SECONDS")
    if not value:
        return DEFAULT_LLM_TIMEOUT_SECONDS
    try:
        return float(value)
    except ValueError:
        return DEFAULT_LLM_TIMEOUT_SECONDS


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "llm", "enabled"}


def _clean_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    if not values:
        return []
    return sorted({str(value).strip() for value in values if str(value).strip()}, key=str.casefold)[:200]


def _clean_known_dates(values: list[str] | tuple[str, ...] | None) -> list[str]:
    dates: set[str] = set()
    for value in values or ():
        try:
            dates.add(normalize_date(str(value)))
        except ValueError:
            continue
    return sorted(dates)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_date(value: Any, known_dates: list[str] | tuple[str, ...] | None) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    try:
        return normalize_date(text)
    except ValueError:
        pass

    if re.fullmatch(r"\d{1,2}", text):
        day = int(text)
        matches = [date for date in _clean_known_dates(known_dates) if int(date.split("-", maxsplit=1)[0]) == day]
        if len(matches) == 1:
            return matches[0]
    return None


def _canonical_cctv_id(value: Any) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    try:
        return normalize_cctv_id(text)
    except ValueError:
        return None


def _canonical_time(value: Any) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    try:
        return normalize_time(text)
    except ValueError:
        return None


def _canonical_known(value: Any, known_values: list[str] | tuple[str, ...] | None) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    candidates = _clean_list(known_values)
    exact = {candidate.casefold(): candidate for candidate in candidates}
    if text.casefold() in exact:
        return exact[text.casefold()]

    loose_text = _loose_key(text)
    for candidate in candidates:
        if _loose_key(candidate) == loose_text:
            return candidate
    return text


def _canonical_colors(payload: dict[str, Any], known_colors: list[str] | tuple[str, ...] | None) -> list[str]:
    raw_colors = payload.get("colors")
    if raw_colors is None:
        raw_colors = payload.get("color")
    if raw_colors is None:
        return []
    if isinstance(raw_colors, str):
        color_values = re.split(r"\s*(?:,|/|\band\b|\bor\b)\s*", raw_colors, flags=re.IGNORECASE)
    elif isinstance(raw_colors, list):
        color_values = raw_colors
    else:
        color_values = [raw_colors]

    colors: list[str] = []
    for value in color_values:
        color = _canonical_known(value, known_colors)
        if color and color not in colors:
            colors.append(color)
    return colors


def _canonical_vehicle_type(value: Any) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    for vehicle_type in VEHICLE_TYPES:
        if text.casefold() == vehicle_type.casefold():
            return vehicle_type
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "on"}


def _loose_key(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value.casefold())
