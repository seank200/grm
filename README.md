# GRM: Git Repository Manager

Mange local git repositories

## Prerequisites

- Python `3.10` or higher

## Install

Install in an isolated runtime environment, such as [pipx](https://github.com/pypa/pipx)

```bash
git clone https://github.com/seank200/grm.git
pipx install grm
grm --help
```

## Commands

- `find`: Recursively search for git repositories in a directory
- `status`: Show working tree status of repositories
- `switch`: Fetch from remote repositories
- `fetch`: Switch repositories to target ref
- `sync`: Push to and pull from remote repositories

## Documentation

Run `grm <command> --help` for detailed instructions on command usage.
