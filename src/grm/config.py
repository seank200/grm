import dataclasses
from dataclasses import dataclass, field, asdict, is_dataclass
import enum
import json
import logging
from pathlib import Path
import sys
import types
from collections.abc import Mapping, Sequence
from typing import (
    Annotated, Any, Literal, Union, get_args, get_origin, get_type_hints,
)
import typer
import yaml

from grm.util import GrmException, InvalidArgsError, confirm


GRM_DIR = Path(".grm")
ARCHIVE_DIR = GRM_DIR / "archive"
CONFIG_FILE_NAME = "grmconfig.yaml"
CONFIG_FILE_ENCODING = "utf-8"

app = typer.Typer(help="Manage app configuration")
log = logging.getLogger(__name__)


class RemoteProvider(enum.Enum):
    GITHUB = "github"


class ConfigFileFormat(enum.Enum):
    YAML = "yaml"
    JSON = "json"

    @property
    def suffix(self) -> str:
        return f".{self.value}"


@dataclass
class CloneOptions:
    owner: str
    """Remote repository owner (account or organization/group name)"""

    provider: str = "github"
    """Remote repository provider name (possible values: 'github')"""

    hostname: str | None = None
    """Hostname of the remote provider (for self-hosted providers)"""

    filters: list[str] = field(default_factory=list)
    """Repository clone URL path filter"""

    path_template: str = "{name}"
    """
    Python template string for local clone directory path
    (supported fields: 'owner', 'name')
    """

    prune: bool = False
    """Permanently delete repositories that no longer exist in remote"""

    archive: bool = True
    """
    Move repositories that no longer exist in remote to an
    archive directory
    """

    batch: bool = False
    """Disable confirmation prompts before pruning repositories"""


@dataclass
class FindOptions:
    depth: int = 0
    """Maximum search recursion depth (0 for no limit)"""

    hidden: bool = False
    """Include hidden files (starting with '.') in search"""

    filters: list[str] = field(default_factory=list)
    """Repository path filter (relative from search root path)"""


@dataclass
class FetchOptions:
    all: bool = False
    prune: bool = False
    tags: bool | None = None
    prune_tags: bool = False


@dataclass
class MergeOptions:
    ff: bool | None = None
    ff_only: bool = False


@dataclass
class SyncOptions:
    clone: list[CloneOptions] = field(default_factory=list)
    find: FindOptions = field(default_factory=FindOptions)
    fetch: FetchOptions = field(default_factory=FetchOptions)
    merge: MergeOptions = field(default_factory=MergeOptions)

    @staticmethod
    def parse(value) -> "SyncOptions":
        return fromdict(value, SyncOptions)


@app.command("init", help="Create a template config file")
def cmd_config_init(
    file_format: Annotated[ConfigFileFormat, typer.Option(
        "-o", "--output",
        help="Output format of config file",
    )] = ConfigFileFormat.YAML,
):
    file_path = (Path.cwd() / CONFIG_FILE_NAME)\
            .with_suffix("." + file_format.value)

    for fmt in ConfigFileFormat:
        existing_path = file_path.with_suffix("." + fmt.value)
        if existing_path.exists():
            if sys.stdin.isatty():
                confirm(f"Overwrite existing config file '{existing_path}'?")
            else:
                raise GrmException(
                    f"Config file already exists at: '{existing_path}'"
                )
            existing_path.unlink()

    options = SyncOptions(clone=[CloneOptions(owner="")])
    options_dict = asdict(options)

    with file_path.open("w", encoding=CONFIG_FILE_ENCODING) as file:
        if file_format == ConfigFileFormat.YAML:
            yaml.safe_dump(options_dict, file, allow_unicode=True)

        elif file_format == ConfigFileFormat.JSON:
            json.dump(options_dict, file, indent=2)

        else:
            raise ValueError(f"Invalid output file format: '{file_format}'")

    log.info("Created configuration file template at: %s", file_path)


def fromdict[T](value: dict, dataclass_type: type[T]) -> T:
    """
    Parse raw config value (likely parsed from a JSON or YAML config file)
    and map it to a dataclass
    """

    return _convert(value, dataclass_type, "")


def _convert(value, tp, path: str):
    where = path or "<root>"

    if tp is Any:
        return value

    origin = get_origin(tp)
    args = get_args(tp)

    if origin in (Union, types.UnionType):
        if value is None and type(None) in args:
            return None
        errors = []
        for arg in args:
            if arg is type(None):
                continue
            try:
                return _convert(value, arg, path)
            except InvalidArgsError as e:
                errors.append(str(e))
        raise InvalidArgsError(
            f"Invalid value at '{where}': {'; '.join(errors)}"
        )

    if origin is Literal:
        if value not in args:
            raise InvalidArgsError(
                f"Invalid value at '{where}': expected one of {list(args)}, "
                f"got {value!r}"
            )
        return value

    if origin in (list, set, frozenset, tuple, Sequence):
        if not isinstance(value, (list, tuple)):
            raise InvalidArgsError(
                f"Invalid value at '{where}': expected a list, "
                f"got {type(value).__name__}"
            )
        if origin is tuple and not (len(args) == 2 and args[1] is Ellipsis):
            if args and len(args) != len(value):
                raise InvalidArgsError(
                    f"Invalid value at '{where}': expected {len(args)} items"
                )
            return tuple(
                _convert(v, a, f"{path}[{i}]")
                for i, (v, a) in enumerate(zip(value, args))
            )
        item_type = args[0] if args else Any
        items = [
            _convert(v, item_type, f"{path}[{i}]") for i, v in enumerate(value)
        ]
        return items if origin in (list, Sequence) else origin(items)

    if origin in (dict, Mapping):
        if not isinstance(value, dict):
            raise InvalidArgsError(
                f"Invalid value at '{where}': expected a mapping, "
                f"got {type(value).__name__}"
            )
        key_type, val_type = args if args else (Any, Any)
        return {
            _convert(k, key_type, path): _convert(v, val_type, f"{path}.{k}")
            for k, v in value.items()
        }

    if isinstance(tp, type):
        if is_dataclass(tp):
            return _convert_dataclass(value, tp, path)

        if issubclass(tp, enum.Enum):
            if isinstance(value, tp):
                return value
            try:
                return tp(value)
            except ValueError:
                raise InvalidArgsError(
                    f"Invalid value at '{where}': {value!r} is not one of "
                    f"{[m.value for m in tp]}"
                ) from None

        if tp is float and isinstance(value, int) \
                and not isinstance(value, bool):
            return float(value)

        if not isinstance(value, tp) or (
            tp is int and isinstance(value, bool)
        ):
            raise InvalidArgsError(
                f"Invalid value at '{where}': expected {tp.__name__}, "
                f"got {type(value).__name__}"
            )
        return value

    return value


def _convert_dataclass(value, tp, path: str):
    where = path or "<root>"
    if isinstance(value, tp):
        return value
    if not isinstance(value, dict):
        raise InvalidArgsError(
            f"Invalid value at '{where}': expected a mapping for "
            f"{tp.__name__}, got {type(value).__name__}"
        )

    hints = get_type_hints(tp)
    fields_ = {f.name: f for f in dataclasses.fields(tp) if f.init}

    unknown = set(value) - set(fields_)
    if unknown:
        names = ", ".join(sorted(map(str, unknown)))
        raise InvalidArgsError(f"Unknown option(s) at '{where}': {names}")

    kwargs = {}
    for name, f in fields_.items():
        if name in value:
            kwargs[name] = _convert(
                value[name], hints[name], f"{path}.{name}" if path else name
            )
        elif (f.default is dataclasses.MISSING
              and f.default_factory is dataclasses.MISSING):
            raise InvalidArgsError(
                f"Missing required option '{name}' at '{where}'"
            )
    return tp(**kwargs)
