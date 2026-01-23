import logging

from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

from .exceptions import CommandError


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteUrl:
    protocol: str
    host: str
    username: str = ""
    path: str = ""

    @staticmethod
    def parse(url: str) -> "RemoteUrl":
        protocol = ""
        host = ""
        username = ""
        path = ""

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
            path = url[i_colon + 1 :]

            return RemoteUrl(protocol, host, username, path)

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

        return RemoteUrl(protocol, host, username, parsed_url.path)

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

        return s + "\n" if s[-1] == "\n" else "\n\n"

    def owner(self) -> str:
        # "https://some-domain.tld/owner/name.git" -> "owner"
        if not self.path:
            return ""

        remote_path = PurePosixPath(self.path)

        owner = str(remote_path.parent)
        if owner == "." or owner == "/":
            return ""

        return owner

    def name(self) -> str:
        # "https://some-domain.tld/owner/name.git" -> "name"

        if not self.path:
            return ""

        path = PurePosixPath(self.path)
        name = path.stem

        if name.startswith("."):
            name = path.parent.name

        if name == ".":
            return ""

        return name
