import logging
from pathlib import Path

from .requirements import (
    PackageVersion,
    parse_in_file_sources,
    parse_resolved_requirements,
    write_in_file,
)
from .uv import uv_pip_compile

logger = logging.getLogger(__name__)


def _enumerate_build_files(output_dir: Path) -> list[tuple[int, Path, Path]]:
    """Yield (index, in_path, txt_path) for existing requirements-build files."""
    result = []
    i = 0
    while True:
        suffix = "" if i == 0 else f"-{i}"
        in_file = output_dir / f"requirements-build{suffix}.in"
        txt_file = output_dir / f"requirements-build{suffix}.txt"
        if not in_file.exists():
            break
        result.append((i, in_file, txt_file))
        i += 1
    return result


def find_seed_content(package: PackageVersion, output_dir: Path) -> str | None:
    """Find seed content for uv pip compile based on previous run output.

    Matching priority:
    1. Exact name+version match -> that group's .txt
    2. Name-only match -> smallest N group's .txt
    3. No match -> N=0 fallback
    """
    build_files = _enumerate_build_files(output_dir)
    if not build_files:
        return None

    exact_match_n: int | None = None
    name_match_n: int | None = None

    for n, in_path, _txt_path in build_files:
        sources = parse_in_file_sources(in_path)
        for name, version in sources:
            if name == package.name and version == package.version:
                exact_match_n = n
                break
            if name == package.name and (name_match_n is None or n < name_match_n):
                name_match_n = n
        if exact_match_n is not None:
            break

    if exact_match_n is not None:
        chosen_n = exact_match_n
    elif name_match_n is not None:
        chosen_n = name_match_n
    else:
        chosen_n = 0

    suffix = "" if chosen_n == 0 else f"-{chosen_n}"
    txt_file = output_dir / f"requirements-build{suffix}.txt"
    if txt_file.exists():
        logger.debug("Seeding %s from requirements-build%s.txt", package.key, suffix)
        return txt_file.read_text()

    return None


def resolve_build_deps(
    package: PackageVersion,
    build_deps: list[str],
    work_dir: Path,
    exclude_newer: str | None = None,
    seed_content: str | None = None,
) -> dict[str, str]:
    """Resolve build dependency specifiers to pinned versions.

    Writes the specifiers to {work_dir}/{package.key}.in, runs
    uv pip compile to produce {work_dir}/{package.key}.txt, and
    returns {canonical_name: version}.
    """
    in_file = work_dir / f"{package.key}.in"
    txt_file = work_dir / f"{package.key}.txt"

    write_in_file(in_file, build_deps)
    if seed_content:
        txt_file.write_text(seed_content)
    uv_pip_compile(in_file, txt_file, exclude_newer=exclude_newer)

    return parse_resolved_requirements(txt_file.read_text())
