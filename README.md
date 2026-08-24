# slushy-build

slushy-build is a framework for building a Python package with
no binary builds with all the dependencies locked in git.
It's meant to be used together with
[Hermeto](https://github.com/hermetoproject/hermeto)
and [Renovate](https://github.com/renovatebot/renovate).

## Overview

The basic way that slushy-build works is that you have a source
of truth for binary dependencies, typically `uv.lock`, and
slushy build creates and maintains `requirements.in` and
`requirements.txt` format files for build dependencies based on that:

```
# The source of truth
uv.lock
# Exported requirements from the project
.konflux/requirements.txt
# Packages required to build the packages in requirements.txt from source
.konflux/reqirements-build.in
.konflux/reqirements-build.txt
# Additional requirements that conflict with those in reqirements-build.txt
.konflux/reqirements-build-1.in
.konflux/reqirements-build-1.txt
# And more conflicting requirements...
.konflux/reqirements-build-2.in
.konflux/reqirements-build-2.txt
...
```

## Installation

Install with `uv tool install slushy-build` or run directly wth `uvx slushy-build`. `uv` is used for dependency compilation, so must already be available on the system.

## Usage

```
slushy-build update [--from-scratch] [--uv-lock | -r <REQUIREMENTS_FILE>] [--uv-directory DIRECTORY] [--exclude-newer <EXCLUDE_NEWER>] [--no-update-pipeline] [--pipeline-dir DIRECTORY]
```

 * **`--from-scratch`** - ignore existing requirements.txt and start over from scratch.
 * **`--exclude-newer`** - ignore dependencies newer than specified - passed to `uv pip compile` when resolving dependencies.
 * **`--uv-lock`** - use uv.lock in the current directory as starting point for package versions needed.
 * **`--uv-directory`** directory to find uv.lockin
 * **`-r`** - use a requirements.txt file as the starting point for package versions
 * **`--update-pipeline` / `--no-update-pipeline`** - after generating requirements, sync the `prefetch-input` parameter of any Tekton `PipelineRun` files so its `pip` entry points at the generated requirements files. Enabled by default.
 * **`--pipeline-dir`** - directory to scan for Tekton `PipelineRun` `.yaml` files (default: `.tekton`).

### Pipeline sync

When `--update-pipeline` is enabled and `--pipeline-dir` exists, each `*.yaml` file in it is inspected. For files that are a `kind: PipelineRun` with a `prefetch-input` parameter, the `pip` entry of the JSON prefetch config is updated in place (preserving comments and formatting) so that `requirements_build_files` lists the generated `requirements-build*.txt` files, and (when building from `--uv-lock`) `requirements_files` points at the generated `requirements.txt`. A missing `pip` entry is added.

 * A file that is not valid YAML, or a `PipelineRun` with no `prefetch-input` parameter, is warned about and skipped.
 * A `prefetch-input` value that is not valid JSON, is not a list of objects, or whose scalar cannot be located for an in-place edit (e.g. a double-quoted or block scalar), is a hard error.

## Algorithm

 0. If the package version source is `uv.lock`, use `uv export` to export a requirements.txt
 1. Initialize the resolved package set to the package versions in the source
 2. Loop until we're not adding any more packages:
  1. Find the build requirements for all new packages in the resolved package set (using pybuild-deps)
  1. Individually `uv pip compile` to resolve the requirements to binary packages. Synthesize fake existing requirements.txt with seed versions that are based on the versions in the existing .konflux/requirements-build-*.txt, unless `--from-scratch` is specified. (Use a magic comment in the requirements-build.in to track what packages it is derived from.)
 3. Examine the package versions in all the resolved packages to find out what packages are compatible with what other packages.
 4. Loop:
  1. determine the largest possible set of packages that are compatible with each other (using networkx.find_cliques). There will likely be multiple such - tie break by picking the one with the newest versions.
  1. write that into a `requirements-build.in`file, remove the packages from the package set.
 5. Call `uv pip compile` on all the `requirements-build.in` files to update the `requirements-build.txt`
