#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract file history from git

Usage:
  extract_git_history.py --input <file-path> --output <output-path> [--start-at <commit>]
  extract_git_history.py (-h | --help)
  extract_git_history.py --version

Options:
  -h, --help                    Show this screen.
  --version                     Show version.
  -i, --input <file-path>       Path to the git controlled file.
  -o, --output <output-path>    Path to the output file.
  -s, --start-at <commit>       SHA of the start commit.

"""

from docopt import docopt
import git
import jsonlines
import json
from pathlib import Path


arguments = docopt(__doc__, version='extract_git_history.py 1.0')


def iterate_file_versions(filepath, start_commit=None):
    ref = "main"
    relative_path = str(Path(filepath).relative_to('.').as_posix())
    repo = git.Repo('.', odbt=git.GitDB)
    commits = reversed(list(repo.iter_commits(ref, paths=[relative_path])))
    for commit in commits:
        try:
            content = commit.tree[relative_path].data_stream.read()
            yield commit.committed_datetime, commit.hexsha, content
        except KeyError:
            # This commit doesn't have a copy of the requested file
            print(f"File not in commit {commit}")
            pass


input_file = arguments["--input"]
output_file = arguments["--output"]
start_at = arguments["--start-at"]

if start_at:
    start = False
else:
    start = True

with jsonlines.open(output_file, mode="w") as writer:
    for git_commit_at, git_hash, content in iterate_file_versions(input_file):
        if git_hash == start_at:
            start = True
        if start:
            versioned_json = json.loads(content)
            versioned_json["_git_committed_datetime"] = git_commit_at.isoformat()
            writer.write(versioned_json)
