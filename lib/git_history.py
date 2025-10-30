import git
from pathlib import Path
import os
import logging


log = logging.getLogger(__name__)
__location__ = os.path.realpath(
    os.path.join(
        os.getcwd(),
        os.path.dirname(__file__)
    )
)
repo_path = os.path.join(__location__, "..")


def iterate_file_versions(filepath, start_commit=None):
    ref = "main"
    relative_path = str((Path(repo_path) / filepath).relative_to(repo_path).as_posix())
    repo = git.Repo(repo_path, odbt=git.GitDB)
    commits = reversed(list(repo.iter_commits(ref, paths=[relative_path])))
    for i, commit in enumerate(commits):
        try:
            content = commit.tree[relative_path].data_stream.read()
            yield i, commit.committed_datetime, commit.hexsha, content
        except KeyError:
            # This commit doesn't have a copy of the requested file
            log.debug(f"File not in commit {commit}")
            pass
