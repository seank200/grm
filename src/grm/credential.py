import logging
import pygit2
import subprocess
import threading

from dataclasses import dataclass
from urllib.parse import urlparse

from .exceptions import ProcedureError
from .remote import RemoteUrl


log = logging.getLogger(__name__)


class RemoteCallbacks(pygit2.RemoteCallbacks):
    def __init__(self) -> None:
        super().__init__()
        self.credentials_cache: dict[
            str, pygit2.Username | pygit2.UserPass | pygit2.Keypair | None
        ] = {}
        self.lock = threading.Lock()

    def credentials(
        self,
        url: str,
        username_from_url: str | None,
        allowed_types: pygit2.CredentialType,
    ) -> pygit2.Username | pygit2.UserPass | pygit2.Keypair:
        try:
            remote_url = RemoteUrl.parse(url)
        except Exception as e:
            raise ProcedureError(f"Invalid remote URL '{url}'")

        with self.lock:
            if remote_url in self.credentials_cache:
                cached = self.credentials_cache.get(remote_url.unparse())

                if cached is None:
                    raise ProcedureError(
                        "No credentials found for '{}'".format(remote_url.unparse)
                    )
                else:
                    return cached

        if bool(allowed_types & pygit2.CredentialType.USERPASS_PLAINTEXT):
            # ask git-credential for credentials
            return self._credentials_userpass_plaintext(remote_url)

        if bool(allowed_types & pygit2.CredentialType.SSH_KEY):
            # delegate to ssh-agent
            return self._credentials_ssh_key(remote_url, url, username_from_url)

        raise ProcedureError(
            "Unsupported remote credential type '{}'".format(allowed_types.name)
        )

    def _credentials_userpass_plaintext(self, remote_url: RemoteUrl):
        try:
            proc = subprocess.run(
                "git credential fill".split(" "),
                input=remote_url.git_credential_in(),
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise ProcedureError(
                "Failed to load credentials for '{}' ({})".format(
                    remote_url.unparse(), e.returncode
                )
            )
        except KeyboardInterrupt:
            with self.lock:
                self.credentials_cache[remote_url.unparse()] = None

            raise ProcedureError(
                "Credential load for '{}' aborted by user".format(remote_url.unparse())
            )

        result: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            key, value = line.split("=", 1)
            result[key] = value

        if "username" in result and "password" in result:
            userpass = pygit2.UserPass(
                username=result["username"],
                password=result["password"],
            )

            log.debug("fetch: Obtained credentials for: %s", remote_url.unparse())

            with self.lock:
                self.credentials_cache[remote_url.unparse()] = userpass

            return userpass
        else:
            # unexpected invalid output from git-credential
            with self.lock:
                self.credentials_cache[remote_url.unparse()] = None

            raise ProcedureError(
                "No credentials found for '{}'".format(remote_url.unparse())
            )

    def _credentials_ssh_key(
        self, remote_url: RemoteUrl, url: str, username_from_url: str | None
    ):
        with self.lock:
            if remote_url in self.credentials_cache:
                cached = self.credentials_cache.get(remote_url.unparse())
                if cached is not None:
                    return cached
            else:
                self.credentials_cache[remote_url.unparse()] = None
                log.warning(
                    "remote: Delegating to ssh-agent for SSH "
                    "credentials (this will fail if ssh-agent is "
                    "not already running on your machine)",
                    url,
                )

        return pygit2.KeypairFromAgent(
            remote_url.username or username_from_url or "git"
        )
