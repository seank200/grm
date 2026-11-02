from collections.abc import Mapping
from dataclasses import MISSING, Field, dataclass, field, fields, is_dataclass
from enum import Enum
import json
import logging
import os
from pathlib import Path
import stat
import sys
from types import UnionType
from typing import (
    Any,
    ClassVar,
    Protocol,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)
import yaml

from grm.util import ConsoleHandler, InvalidConfigError


FILE_NAME = ".grmconfig"
FILE_ENCODING = "utf-8"
FILE_EXTENSIONS = ["", ".yaml", ".yml", ".json"]


class RemoteProvider(Enum):
    GITHUB = "github"


@dataclass
class CloneOptions:
    owner: str
    provider: str = "github"
    prune: bool = False
    globs: list[str] = field(default_factory=list)


@dataclass
class FindOptions:
    depth: int = 0
    hidden: bool = False
    globs: list[str] = field(default_factory=list)


@dataclass
class FetchOptions:
    prune: bool = False
    tags: bool | None = None
    prune_tags: bool = False
    all: bool = False


@dataclass
class MergeOptions:
    ff: bool | None = None
    ff_only: bool = False


@dataclass
class SyncOptions:
    path: Path
    clone: list[CloneOptions] = field(default_factory=list)
    find: FindOptions = field(default_factory=FindOptions)
    fetch: FetchOptions = field(default_factory=FetchOptions)
    merge: MergeOptions = field(default_factory=MergeOptions)


@dataclass
class Config:
    sync: list[SyncOptions] = field(default_factory=list)


class _DataclassInstance(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Field[object]]]


DataclassT = TypeVar("DataclassT", bound=_DataclassInstance)


config = Config()
log = logging.getLogger(__name__)


def load_config() -> Config | None:
    result = _find_config_file()
    if result is None:
        log.debug("Config file '%s' not found", FILE_NAME)
        return None

    file_path, file_stat = result
    if file_path:
        data = _load_config_file(file_path, file_stat)
        if data:
            config = _parse_config(data)
            log.debug("Loaded config from file '%s'. %r", file_path, config)
            return config


def get_config() -> Config:
    return config


def configure(
    *,
    cwd: Path | None,
    debug: bool,
    quiet: bool,
    color: bool | None,
):
    global config

    if cwd:
        os.chdir(cwd)

    logger = logging.getLogger(__name__.split(".", 1)[0])

    if debug:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.INFO
    logger.setLevel(level)

    handler = ConsoleHandler(sys.stderr, color=color)
    logger.addHandler(handler)

    file_config = load_config()
    if file_config:
        config = file_config
    else:
        log.debug("Using default config: %r", config)


def _find_config_file() -> tuple[Path, os.stat_result] | None:
    path: Path = Path.cwd()
    parent: Path | None = None

    while path != parent or parent is None:
        for suffix in FILE_EXTENSIONS:
            file_path = (path / FILE_NAME).with_suffix(suffix)

            try:
                file_stat = file_path.stat()
            except FileNotFoundError:
                continue

            file_mode = file_stat.st_mode

            if not file_mode & stat.S_IRUSR:
                log.debug("Ignoring file '%s' (no read permission)", file_path)
                continue

            if not stat.S_ISREG(file_mode):
                log.debug("Ignoring file '%s' (not a regular file)", file_path)
                continue

            return file_path, file_stat

        path = path.parent
        parent = path.parent


def _load_config_file(file_path: Path, file_stat: os.stat_result):
    if file_stat.st_size == 0:
        log.debug("Found empty config file '%s'", file_path)
        return None

    suffix = file_path.suffix

    try:
        with file_path.open("r", encoding=FILE_ENCODING) as file:
            if suffix in ("", ".yaml", ".yml"):
                try:
                    return yaml.safe_load(file)
                except yaml.YAMLError as exc:
                    raise InvalidConfigError(
                        f"Invalid YAML. {exc}",
                        file=file_path,
                    )

            elif suffix == ".json":
                try:
                    return json.load(file)
                except json.JSONDecodeError as exc:
                    raise InvalidConfigError(
                        f"Invalid JSON. {exc}",
                        file=file_path,
                    )

            else:  # Shouldn't happen
                raise RuntimeError(
                    "Invalid configuration file extension: '%s'",
                    suffix,
                )
    except OSError:
        log.error("Failed to open config file '%s'", file_path)
        raise


def _parse_config(data: object) -> Config:
    """Convert a dictionary loaded from JSON or YAML into a Config."""
    return _parse_dataclass(data, Config, "")


def _parse_dataclass(
    data: object,
    target: type[DataclassT],
    field_path: str,
) -> DataclassT:
    data = _parse_mapping(data, field_path)

    target_fields = {item.name: item for item in fields(target)}
    unknown_fields = data.keys() - target_fields.keys()
    if unknown_fields:
        name = sorted(unknown_fields)[0]
        raise InvalidConfigError(
            "unknown property",
            _join_path(field_path, name)
        )

    type_hints = get_type_hints(target)
    values: dict[str, object] = {}
    for name, dataclass_field in target_fields.items():
        path = _join_path(field_path, name)
        if name in data:
            values[name] = _parse_value(data[name], type_hints[name], path)
        elif (
            dataclass_field.default is MISSING
            and dataclass_field.default_factory is MISSING
        ):
            raise InvalidConfigError("missing required property", path)

    return target(**values)


def _parse_mapping(
    value: object,
    field_path: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise InvalidConfigError(
            f"expected an object, got {type(value).__name__}",
            field_path,
        )

    mapping = cast(Mapping[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise InvalidConfigError("expected string property names", field_path)

    return cast(Mapping[str, object], mapping)


def _parse_value(value: Any, target: Any, field_path: str) -> Any:
    origin = get_origin(target)

    if origin is list:
        if not isinstance(value, list):
            raise _type_error(field_path, "an array", value)
        item_type = get_args(target)[0]
        return [
            _parse_value(item, item_type, f"{field_path}[{index}]")
            for index, item in enumerate(value)
        ]

    if origin is UnionType:
        union_types = get_args(target)
        if value is None and type(None) in union_types:
            return None

        non_none_types = [
            union_type
            for union_type in union_types
            if union_type is not type(None)
        ]
        if len(non_none_types) == 1:
            return _parse_value(value, non_none_types[0], field_path)

    if isinstance(target, type) and is_dataclass(target):
        return _parse_dataclass(value, target, field_path)

    if target is Path:
        if not isinstance(value, str):
            raise _type_error(field_path, "a string path", value)
        return Path(value)

    if isinstance(target, type) and issubclass(target, Enum):
        try:
            return target(value)
        except (TypeError, ValueError) as exc:
            allowed = ", ".join(repr(item.value) for item in target)
            raise InvalidConfigError(
                f"expected one of {allowed}",
                field_path,
            ) from exc

    if target is Any:
        return value

    if target in (bool, int, float, str) and type(value) is not target:
        raise _type_error(field_path, target.__name__, value)

    return value


def _type_error(
    field_path: str,
    expected: str,
    value: Any,
) -> InvalidConfigError:
    return InvalidConfigError(
        f"expected {expected}, got {type(value).__name__}",
        field_path,
    )


def _join_path(parent: str, child: str) -> str:
    if not parent:
        return child
    return f"{parent}.{child}"
