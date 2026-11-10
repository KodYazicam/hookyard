"""Named replay targets with optional request signing.

Presets deliberately never contain secrets: signing reuses the secrets that
were already passed to the inspector on the command line or environment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .signatures import SIGN_PROVIDERS


@dataclass(frozen=True)
class ReplayPreset:
    name: str
    target: str
    sign: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"name": self.name, "target": self.target, "sign": self.sign}


def load_presets(path: str | Path) -> list[ReplayPreset]:
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read presets file {file}: {error.strerror or error}") from error
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{file} is not valid JSON: {error.msg} (line {error.lineno})"
        ) from error

    if isinstance(raw, dict):
        entries = raw.get("presets")
    elif isinstance(raw, list):
        entries = raw
    else:
        entries = None
    if not isinstance(entries, list):
        raise ValueError(f"{file} must contain a 'presets' list")

    presets: list[ReplayPreset] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"preset #{index + 1} must be an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"preset #{index + 1} needs a non-empty name")
        name = name.strip()
        if name in seen:
            raise ValueError(f"duplicate preset name {name!r}")
        target = entry.get("target")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"preset {name!r} needs a target URL")
        target = target.strip()
        parts = urlsplit(target)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError(f"preset {name!r} target must be an http(s) URL")
        sign = entry.get("sign")
        if sign is not None:
            if not isinstance(sign, str) or sign.lower() not in SIGN_PROVIDERS:
                allowed = ", ".join(sorted(SIGN_PROVIDERS))
                raise ValueError(
                    f"preset {name!r} sign must be one of: {allowed}"
                )
            sign = sign.lower()
        seen.add(name)
        presets.append(ReplayPreset(name=name, target=target, sign=sign))
    return presets
