"""Strict local model profiles for the real WeKnora live environment."""

from dataclasses import dataclass, field
from pathlib import Path
from stat import S_IMODE
from urllib.parse import urlsplit

from pydantic import SecretStr

_ROLE_PREFIXES = (
    "LOCAL_LIVE_WEKNORA_CHAT",
    "LOCAL_LIVE_WEKNORA_EMBEDDING",
    "LOCAL_LIVE_WEKNORA_RERANK",
)
_REQUIRED_KEYS = frozenset(
    {
        *(
            f"{prefix}_{suffix}"
            for prefix in _ROLE_PREFIXES
            for suffix in ("BASE_URL", "API_KEY", "MODEL")
        ),
        "HARNESS_LLM_BASE_URL",
        "HARNESS_LLM_API_KEY",
        "HARNESS_LLM_MODEL_WEAK",
    }
)
_SENSITIVE_SUFFIXES = ("_API_KEY", "_TOKEN", "_PASSWORD", "_SECRET")


@dataclass(frozen=True)
class ModelProfile:
    base_url: str = field(repr=False)
    api_key: SecretStr
    model: str


@dataclass(frozen=True)
class LocalLiveConfig:
    weknora_chat: ModelProfile
    weknora_embedding: ModelProfile
    weknora_rerank: ModelProfile
    extraction: ModelProfile


def _values(path: Path) -> dict[str, str]:
    if S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("local-live credential file permission must be 0600")
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator:
            raise ValueError("invalid local-live setting syntax")
        key = name.strip()
        if key in values:
            raise ValueError(f"duplicate local-live setting: {key}")
        values[key] = value.strip()
    return values


def _profile(values: dict[str, str], prefix: str) -> ModelProfile:
    base_url_key = f"{prefix}_BASE_URL"
    base_url = _validated_base_url(base_url_key, values[base_url_key])
    return ModelProfile(
        base_url=base_url,
        api_key=SecretStr(values[f"{prefix}_API_KEY"]),
        model=values[f"{prefix}_MODEL"],
    )


def _validated_base_url(key: str, value: str) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        raise ValueError(f"{key} must be a valid HTTPS base URL") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{key} must be a valid HTTPS base URL")
    return value


def load_local_live_config(path: Path) -> LocalLiveConfig:
    values = _values(path)
    unknown_sensitive = sorted(
        key
        for key in values.keys() - _REQUIRED_KEYS
        if key.endswith(_SENSITIVE_SUFFIXES)
    )
    if unknown_sensitive:
        raise ValueError(f"unknown security-sensitive setting: {unknown_sensitive[0]}")
    empty = sorted(key for key in _REQUIRED_KEYS if not values.get(key, "").strip())
    if empty:
        raise ValueError(f"EMPTY required setting: {empty[0]}")
    extraction_base_url = _validated_base_url(
        "HARNESS_LLM_BASE_URL", values["HARNESS_LLM_BASE_URL"]
    )
    return LocalLiveConfig(
        weknora_chat=_profile(values, "LOCAL_LIVE_WEKNORA_CHAT"),
        weknora_embedding=_profile(values, "LOCAL_LIVE_WEKNORA_EMBEDDING"),
        weknora_rerank=_profile(values, "LOCAL_LIVE_WEKNORA_RERANK"),
        extraction=ModelProfile(
            base_url=extraction_base_url,
            api_key=SecretStr(values["HARNESS_LLM_API_KEY"]),
            model=values["HARNESS_LLM_MODEL_WEAK"],
        ),
    )
