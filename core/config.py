from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def load_simple_yaml(path: str | Path) -> Dict[str, Any]:
    """Читает простой config.yaml вида `key: value` без внешних зависимостей.

    Этого достаточно для параметров MVP. Вложенные секции и списки намеренно
    не поддерживаются, чтобы не добавлять PyYAML в минимальные зависимости.
    """

    config_path = Path(path)
    if not config_path.exists():
        return {}

    values: Dict[str, Any] = {}
    for line_number, raw_line in enumerate(config_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Ошибка config.yaml в строке {line_number}: ожидался формат key: value")

        key, value = line.split(":", 1)
        key = key.strip().replace("-", "_")
        value = _strip_inline_comment(value.strip())
        values[key] = _parse_scalar(value)

    return values


def _strip_inline_comment(value: str) -> str:
    quote = None
    result = []
    for char in value:
        if char in ("'", '"'):
            quote = None if quote == char else char
        if char == "#" and quote is None:
            break
        result.append(char)
    return "".join(result).strip()


def _parse_scalar(value: str) -> Any:
    if value == "":
        return None

    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"none", "null"}:
        return None

    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]

    try:
        if any(marker in value.lower() for marker in (".", "e")):
            return float(value)
        return int(value)
    except ValueError:
        return value

