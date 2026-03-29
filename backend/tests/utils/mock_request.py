from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _pick_first_enum(schema: Dict[str, Any]) -> Any:
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    return None


def _default_for_type(t: Optional[str]) -> Any:
    if t == "string":
        return "dummy"
    if t == "number":
        return 1.0
    if t == "integer":
        return 1
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return {}
    return None


def _gen_from_schema(schema: Dict[str, Any], depth: int = 0, max_depth: int = 6) -> Any:
    """
    Very small JSON-schema-ish generator good enough for FastAPI OpenAPI schemas.
    Generates ONLY required fields unless defaults/enums force values.
    """
    if depth > max_depth:
        return None

    # $ref handled outside
    if "oneOf" in schema:
        return _gen_from_schema(schema["oneOf"][0], depth + 1, max_depth)
    if "anyOf" in schema:
        return _gen_from_schema(schema["anyOf"][0], depth + 1, max_depth)
    if "allOf" in schema:
        # merge naïvely: take first for generation
        return _gen_from_schema(schema["allOf"][0], depth + 1, max_depth)

    if "default" in schema:
        return schema["default"]

    enum_val = _pick_first_enum(schema)
    if enum_val is not None:
        return enum_val

    t = schema.get("type")

    if t == "object" or "properties" in schema:
        props = schema.get("properties", {})
        required: List[str] = schema.get("required", [])
        obj: Dict[str, Any] = {}

        for k in required:
            if k in props:
                obj[k] = _gen_from_schema(props[k], depth + 1, max_depth)
            else:
                obj[k] = None

        # If there are no required fields, generate a minimal object
        if not obj and props:
            # pick 1 property to avoid empty payloads sometimes rejected
            first_key = next(iter(props.keys()))
            obj[first_key] = _gen_from_schema(props[first_key], depth + 1, max_depth)

        return obj

    if t == "array":
        items = schema.get("items", {"type": "string"})
        return [_gen_from_schema(items, depth + 1, max_depth)]

    # primitives
    val = _default_for_type(t)
    return val


def _resolve_ref(openapi: Dict[str, Any], ref: str) -> Dict[str, Any]:
    # ref format: "#/components/schemas/ModelName"
    path = ref.lstrip("#/").split("/")
    node: Any = openapi
    for p in path:
        node = node[p]
    return node


def _resolve_operation(openapi: Dict[str, Any], path: str, method: str) -> Dict[str, Any]:
    method = method.lower()
    paths = openapi.get("paths", {})

    # 1) exact path
    if path in paths and method in paths[path]:
        return paths[path][method]

    # 2) common API prefix compatibility
    candidates = [path]
    if not path.startswith("/api/"):
        candidates.append(f"/api{path}")
    if path.startswith("/api/"):
        candidates.append(path.replace("/api", "", 1))

    for candidate in candidates:
        if candidate in paths and method in paths[candidate]:
            return paths[candidate][method]

    # 3) fallback: match by trailing segment, prefer evaluate endpoint
    tail = path.rstrip("/").split("/")[-1]
    for p, item in paths.items():
        if method in item and p.rstrip("/").endswith(f"/{tail}"):
            return item[method]

    raise KeyError(f"OpenAPI operation not found for path={path}, method={method}")


def generate_mock_request_from_openapi(
    openapi: Dict[str, Any], path: str = "/evaluate", method: str = "post"
) -> Dict[str, Any]:
    op = _resolve_operation(openapi, path, method)

    content = op["requestBody"]["content"]
    # prefer application/json
    schema = content.get("application/json", next(iter(content.values())))["schema"]

    if "$ref" in schema:
        schema = _resolve_ref(openapi, schema["$ref"])

    payload = _gen_from_schema(schema)

    # Optional: overwrite common fields to realistic values if present
    # (Safe: only touches keys if they exist)
    if isinstance(payload, dict):
        now_iso = datetime.now(timezone.utc).isoformat()
        for k in ["as_of", "asOf", "asOfUtc", "timestamp"]:
            if k in payload and isinstance(payload[k], str):
                payload[k] = now_iso

        # common finance-ish fields
        if "symbol" in payload and isinstance(payload["symbol"], str):
            payload["symbol"] = payload["symbol"] if payload["symbol"] != "dummy" else "SPY"

    return payload
