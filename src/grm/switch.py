import logging
import typer
import subprocess
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Annotated
from .config import get_config
from .git import GitRepo
from .find import find_repos, Matcher
from .utils import max_threads


CMD_TIMEOUT = 60.0

app = typer.Typer()
log = logging.getLogger(__name__)


def _switch_worker(repo: GitRepo, branch: str, detach: bool) -> bool:
    try:
        repo.switch(branch, detach=detach)
    except subprocess.CalledProcessError:
        return False

    return True


@app.command("switch", help="Switch to a branch")
def cmd_switch(
    branch: Annotated[str, typer.Argument(
        help="Branch name"
    )],
    detach: Annotated[bool, typer.Option(
        "--detach",
        help="Allow detached head state when switching",
    )] = False,
):
    config = get_config()

    repos = find_repos(
        config.find_path,
        config.find_max_depth,
        config.include_hidden,
        Matcher(
            query_name=config.query_name,
            query_remote_name=config.query_remote_name,
            query_remote_url=config.query_remote_url,
            query_clean=config.query_clean,
            case_sensitive=config.matcher_case_sensitive,
            exact=config.matcher_exact,
        ),
    )

    with ThreadPoolExecutor(max_workers=max_threads(8, len(repos))) as executor:
        fs = (executor.submit(_switch_worker, repo, branch, detach)
              for repo in repos)
        
        try:
            done_fs = wait(fs, timeout=CMD_TIMEOUT).done
        except KeyboardInterrupt:
            log.warning("Aborting repository switch")
            for f in fs:
                f.cancel()
            raise

        success = 0
        for f in done_fs:
            if f.result() is True:
                success += 1

    log.info("Switched %d repositories to '%s' (total %d)", success, branch, len(done_fs))