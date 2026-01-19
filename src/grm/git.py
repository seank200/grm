import logging
import subprocess
from pathlib import Path
from typing import Optional


GIT_TIMEOUT = 60.0  # seconds


log = logging.getLogger(__name__)


class GitRepo:
    def __init__(self, path: Path):
        self.path = path
        self._remotes: Optional[dict[str, str]] = None

    @property
    def name(self) -> str:
        return self.path.name

    def remotes(self) -> dict[str, str]:
        if self._remotes is not None:
            return self._remotes

        proc = self.run("git remote -v".split(" "))

        remotes: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            try:
                name_end = line.index("\t")
                name = line[:name_end]

                if name in remotes:
                    continue

                url_end = line.index(" (", name_end)
                url = line[name_end+1:url_end]

                remotes[name] = url
            except ValueError:
                log.debug("(%s) invalid git-remote line: %s", self.path, line)

        self._remotes = remotes
        return remotes

    def run(self, args, check: bool = True):
        try:
            proc = subprocess.run(
                args,
                cwd=self.path,
                check=check,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )

            if proc.returncode != 0:
                log.debug(
                    "git error (%d): %s$ %s\n%s",
                    proc.returncode,
                    self.path,
                    " ".join(args),
                    proc.stderr,
                )

            return proc
        except subprocess.TimeoutExpired:
            log.error(
                "git command timed out after %f seconds: %s$ %s",
                GIT_TIMEOUT,
                self.path,
                " ".join(args),
            )
            raise
        except subprocess.CalledProcessError as e:
            log.debug(
                "git error (%d): %s$ %s\n%s",
                e.returncode,
                self.path,
                " ".join(args),
                e.stderr,
            )
            raise
