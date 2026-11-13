import json
import logging
from pathlib import Path
import typer
from typing import Annotated, Optional
import yaml

from grm.config import (
    SyncOptions,
    ConfigFileFormat,
    CONFIG_FILE_NAME,
    CONFIG_FILE_ENCODING,
)
from grm.clone import clone_repos
from grm.fetch import fetch_repos
from grm.find import find_repos
from grm.merge import merge_repos
from grm.util import GrmException, InvalidArgsError


app = typer.Typer()
log = logging.getLogger(__name__)


@app.command("sync", help="Synchronize changes with remote")
def cmd_sync(
    config_file: Annotated[Optional[Path], typer.Option(
        "-f", "--filename",
        file_okay=True,
        help="Path to sync options file",
    )] = None,
):
    config_file = config_file or _resolve_config_file(Path.cwd())
    options = _parse_options(config_file)
    sync_repos(config_file.parent, options)


def sync_repos(workspace: Path, options: SyncOptions):
    cloned_repos = clone_repos(workspace, options.clone)
    found_repos = find_repos(workspace, options.find)
    fetched_repos = fetch_repos(workspace, found_repos, options.fetch)
    merged_repos = merge_repos(workspace, fetched_repos, options.merge)

    if cloned_repos or merged_repos:
        if log.isEnabledFor(logging.INFO):
            n_success = len(cloned_repos) + len(merged_repos)
            cloned_paths = [
                str(repo.path.relative_to(workspace))
                for repo in cloned_repos + merged_repos
            ]
            cloned_paths.sort()

            log.info(
                "Synchronized %d %s: %s",
                n_success,
                "repository" if n_success <= 1 else "repositories",
                ", ".join(cloned_paths)
            )
    else:
        log.warning("Nothing to sync.")


def _parse_options(file_path: Path) -> SyncOptions:
    with file_path.open("r", encoding=CONFIG_FILE_ENCODING) as file:
        if file_path.suffix == ConfigFileFormat.YAML.suffix:
            try:
                data = yaml.safe_load(file)
            except yaml.YAMLError as exc:
                raise InvalidArgsError("Invalid YAML", file=file_path) from exc

        elif file_path.suffix == ConfigFileFormat.JSON.suffix:
            try:
                data = json.load(file)
            except json.JSONDecodeError as exc:
                raise InvalidArgsError("Invalid JSON", file=file_path) from exc

        else:
            raise GrmException(
                f"Unsupported config file extension: '{file_path.suffix}'"
            )

    if type(data) is not dict:
        raise InvalidArgsError(
            "Config file must contain an object",
            file=file_path,
        )

    return SyncOptions.parse(data)


def _resolve_config_file(start: Path) -> Path:
    path = start
    parent: Path | None = None

    while path != parent or parent is None:
        for file_format in ConfigFileFormat:
            config_file_path = (path / CONFIG_FILE_NAME)\
                .with_suffix(file_format.suffix)

            try:
                if config_file_path.is_file():
                    return config_file_path
            except PermissionError:
                raise GrmException(
                    f"No permission to read metadata of '{config_file_path}'"
                )
            except TimeoutError:
                raise GrmException(
                    "Operation timed out while reading metadata of "
                    f"'{config_file_path}'"
                )
            except OSError:
                raise GrmException(
                    f"Failed to read metadata of '{config_file_path}'",
                )

        path = path.parent
        parent = path.parent

    raise GrmException(f"Config file '{CONFIG_FILE_NAME}' not found")
