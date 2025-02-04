"""
Copyright 2022 Booz Allen Hamilton
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

from git import Repo
from git.exc import GitCommandError
from mkdocs.config import config_options as c
from mkdocs.config.base import Config
from mkdocs.exceptions import PluginError
from mkdocs.structure.pages import Page
from mkdocs.utils import warning_filter

log = logging.getLogger("mkdocs.plugins." + __name__)
log.addFilter(warning_filter)

@dataclass
class GitRepoConfig:
    """Configuration for Git repository operations."""
    url: str
    branch: str
    include: List[str]
    repo_path: Path

class RepoItem(Config):
    """
    Represents a repository defined by the user.
    Handles repository configuration, cloning, and symlink creation.
    """

    url = c.Optional(c.Type(str))
    branch = c.Type(str, default="main")
    include = c.ListOfItems(c.Type(str), default=[])
    path = c.Optional(c.Type(str))

    def __post_init__(self) -> None:
        """Initialize repository name after configuration."""
        self.repo_name: Optional[str] = None
        self.do_validation()

    def do_validation(self) -> None:
        """
        Validate user configuration.
        
        Raises:
            PluginError: If configuration is invalid.
        """
        if not (bool(self.url) ^ bool(self.path)):
            raise PluginError(
                'Repository must define either a URL or a path, but not both'
            )

    def fetch(self, temp_dir: Union[str, Path], first_build: bool) -> None:
        """
        Add repository contents to temporary directory.
        
        Args:
            temp_dir: Directory to store repository contents
            first_build: Flag indicating if this is the first build
        """
        temp_dir = Path(temp_dir)
        if self.url:
            self._clone_git_repo(temp_dir, first_build)
        else:
            self._create_symlink(temp_dir)

    def _clone_git_repo(self, temp_dir: Path, first_build: bool) -> None:
        """
        Clone a remote git repository.
        
        Args:
            temp_dir: Directory to clone repository into
            first_build: Flag indicating if this is the first build
        
        Raises:
            PluginError: If branch doesn't exist or clone fails
        """
        try:
            self.repo_name = self.url.split("/")[-1].replace('.git', '')
            repo_path = temp_dir / self.repo_name

            if repo_path.exists():
                log.info(f'Git pull: {self.url}')
                repo = Repo(repo_path)
                repo.remotes.origin.pull()
                return

            if self.include:
                self._clone_with_sparse_checkout(repo_path)
            else:
                self._clone_full_repo(repo_path)

        except GitCommandError as e:
            raise PluginError(f'Git operation failed: {str(e)}') from e

    def _clone_with_sparse_checkout(self, repo_path: Path) -> None:
        """
        Clone repository with sparse checkout for specific files.
        
        Args:
            repo_path: Path to clone repository into
        """
        cloned_repo = Repo.clone_from(self.url, repo_path, no_checkout=True)
        if not self._branch_exists(cloned_repo, self.branch):
            raise PluginError(
                f'Repository {self.url} does not have branch {self.branch}'
            )
        cloned_repo.git.checkout(f'origin/{self.branch}', "--", *self.include)

    def _clone_full_repo(self, repo_path: Path) -> None:
        """
        Clone entire repository.
        
        Args:
            repo_path: Path to clone repository into
        """
        cloned_repo = Repo.clone_from(self.url, repo_path)
        if not self._branch_exists(cloned_repo, self.branch):
            raise PluginError(
                f'Repository {self.url} does not have branch {self.branch}'
            )
        cloned_repo.git.checkout(f'origin/{self.branch}')

    @staticmethod
    def _branch_exists(repo: Repo, branch: str) -> bool:
        """
        Check if branch exists in remote repository.
        
        Args:
            repo: Git repository object
            branch: Branch name to check
        
        Returns:
            bool: True if branch exists
        """
        return f'origin/{branch}' in [ref.name for ref in repo.references]

    def set_edit_url(self, page: Page, temp_dir: Union[str, Path]) -> None:
        """
        Set edit URL for pages from remote repositories.
        
        Args:
            page: MkDocs page object
            temp_dir: Temporary directory containing repositories
        """
        if not self.url:
            page.edit_url = None
            return

        prefix = f'{temp_dir}/{self.repo_name}/'
        page.edit_url = ''.join([
            self.url.replace(".git", ""),
            "/edit/",
            f'{self.branch}/',
            page.file.src_path[len(prefix):]
        ])

    def _create_symlink(self, temp_dir: Path) -> None:
        """
        Create symlink within temp_dir to user provided path.
        
        Args:
            temp_dir: Directory to create symlink in
        
        Raises:
            PluginError: If source path doesn't exist
        """
        src = Path(self.path).resolve()
        if not src.exists():
            raise PluginError(f'Path {src} does not exist')

        self.repo_name = src.name
        dst = temp_dir / self.repo_name

        if not dst.exists():
            os.symlink(src, dst, True)
