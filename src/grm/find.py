from grm.git import GitRepo
from pathlib import Path
from typing import Annotated, Optional


class Matcher:
    def __init__(
        self,
        query_name: Optional[str] = None,
        query_remote_name: Optional[str] = None,
        query_remote_url: Optional[str] = None,
        query_clean: Optional[bool] = None,
        case_sensitive: bool = False,
        exact: bool = False,
    ):
        self.query_name = query_name \
            if (not query_name or case_sensitive) \
                else query_name.lower()
        self.query_remote_name = query_remote_name \
            if (not query_remote_name or case_sensitive) \
                else query_remote_name.lower()
        self.query_remote_url = query_remote_url \
            if (not query_remote_url or case_sensitive) \
                else query_remote_url.lower()
        self.query_clean = query_clean
        
        self.case_sensitive = case_sensitive
        self.exact = exact

    def matches_name(self, path: Path) -> bool:
        if not self.query_name:
            return True

        name = path.name if self.case_sensitive else path.name.lower()

        if self.exact:
            return name == self.query_name
        
        return self.query_name in name
    
    def matches_remote(self, repo: GitRepo) -> bool:
        q_name = self.query_remote_name
        q_url = self.query_remote_url

        if not q_name and not q_url:
            return True
        
        for remote_name, remote in repo.get_remotes().items():
            if q_name:
                v_name = remote_name if self.case_sensitive \
                    else remote_name.lower()

                if self.exact:
                    if q_name != v_name:
                        continue
                else:
                    if q_name not in v_name:
                        continue


            if q_url:
                v_url = remote.url if self.case_sensitive \
                    else remote.url.lower()
                if self.exact:
                    if q_url != v_url:
                        continue
                else:
                    if q_url not in v_url:
                        continue

            return True
        
        return False
