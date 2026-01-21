import logging
import pygit2
import subprocess
import threading

from dataclasses import dataclass
from urllib.parse import urlparse

from .exceptions import CommandError, ProcedureError


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteUrl:
    protocol: str
    host: str
    username: str = ""

    @staticmethod
    def parse(url: str) -> "RemoteUrl":
        protocol = ""
        host = ""
        username = ""

        i_colon = url.find(":")
        i_slash = url.find("/")

        if i_colon > i_slash:
            # [user@]host.tld:path/to/repo.git/
            # Like git-fetch, this scp-like syntax is only recognized
            # if there are no slashes before the first colon.
            protocol = "ssh"
            i_at = url.find("@")
            if i_at > 0:
                username = url[:i_at]
            host = url[i_at + 1 : i_colon]

            return RemoteUrl(protocol, host, username)

        parsed_url = urlparse(url)

        if not parsed_url.scheme:
            raise CommandError(f"Invalid remote url: '{url}' -- missing scheme")

        protocol = parsed_url.scheme

        i_at = parsed_url.netloc.find("@")
        if i_at > 0:
            host = parsed_url.netloc[i_at + 1 :]
            i_colon = parsed_url.netloc.find(":")
            if i_colon > 0:
                username = parsed_url.netloc[:i_colon]
            else:
                username = parsed_url.netloc[:i_at]
        else:
            host = parsed_url.netloc

        return RemoteUrl(protocol, host, username)

    def unparse(self) -> str:
        if self.username:
            return f"{self.protocol}://{self.username}@{self.host}"
        return f"{self.protocol}://{self.host}"

    def git_credential_in(self) -> str:
        s = ""
        if self.protocol:
            s += f"protocol={self.protocol}\n"
        if self.host:
            s += f"host={self.host}\n"
        if self.username:
            s += f"username={self.username}\n"

        return s + "\n\n"


class RemoteCallbacks(pygit2.RemoteCallbacks):
    def __init__(self) -> None:
        super().__init__()
        self.credentials_cache: dict[
            RemoteUrl, pygit2.Username | pygit2.UserPass | pygit2.Keypair | None
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

        if remote_url in self.credentials_cache:
            with self.lock:
                cached = self.credentials_cache.get(remote_url)

            if cached is None:
                raise ProcedureError(
                    "No credentials found for '{}'".format(remote_url.unparse)
                )
            else:
                return cached

        if bool(allowed_types & pygit2.CredentialType.USERPASS_PLAINTEXT):
            # ask git-credential for credentials
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
                        remote_url.unparse, e.returncode
                    )
                )
            except KeyboardInterrupt:
                with self.lock:
                    self.credentials_cache[remote_url] = None

                raise ProcedureError(
                    "Credential load for '{}' aborted by user".format(
                        remote_url.unparse
                    )
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
                    self.credentials_cache[remote_url] = userpass

                return userpass
            else:
                with self.lock:
                    self.credentials_cache[remote_url] = None

                raise ProcedureError(
                    "No credentials found for '{}'".format(remote_url.unparse)
                )

        if bool(allowed_types & pygit2.CredentialType.SSH_KEY):
            # delegate to ssh-agent
            return pygit2.KeypairFromAgent(
                remote_url.username or username_from_url or "git"
            )

        raise ProcedureError(
            "Unsupported remote credential type '{}'".format(allowed_types.name)
        )
