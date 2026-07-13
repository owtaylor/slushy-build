import logging
import tempfile
from pathlib import Path

from . import build_deps as build_deps_mod
from .grouping import ResolvedPackageDeps, build_annotations, group_packages, merge_specifiers
from .requirements import (
    PackageVersion,
    filter_requirements,
    parse_requirements,
    write_in_file,
)
from .resolver import find_seed_content, resolve_build_deps
from .uv import uv_export, uv_pip_compile

logger = logging.getLogger(__name__)


def run_update(
    *,
    uv_lock: bool,
    requirements_file: Path | None,
    from_scratch: bool,
    exclude_newer: str | None,
    output_dir: Path,
    annotate_requirements: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 0: Export/load source requirements
    if uv_lock:
        source_text = filter_requirements(uv_export())
        (output_dir / "requirements.txt").write_text(source_text)
    else:
        assert requirements_file is not None
        source_text = filter_requirements(requirements_file.read_text())

    source_packages = parse_requirements(source_text)
    logger.info("Loaded %d source packages", len(source_packages))

    # Step 1-2: Iterative build-dep discovery
    all_known: dict[str, PackageVersion] = {p.key: p for p in source_packages}
    all_resolved: dict[str, ResolvedPackageDeps] = {}
    pending = list(source_packages)

    with tempfile.TemporaryDirectory() as work_dir_str:
        work_dir = Path(work_dir_str)
        iteration = 0
        while pending:
            iteration += 1
            logger.info("Iteration %d: processing %d packages", iteration, len(pending))
            next_pending: list[PackageVersion] = []

            for package in pending:
                try:
                    deps = build_deps_mod.get_build_dependencies(package)
                except build_deps_mod.BuildDependencyError:
                    logger.warning(
                        "Skipping %s: could not determine build dependencies",
                        package.key,
                    )
                    continue

                if not deps:
                    continue

                seed = None if from_scratch else find_seed_content(package, output_dir)

                try:
                    resolved = resolve_build_deps(package, deps, work_dir, exclude_newer, seed_content=seed)
                except Exception:
                    logger.warning(
                        "Skipping %s: resolution failed",
                        package.key,
                        exc_info=True,
                    )
                    continue

                all_resolved[package.key] = ResolvedPackageDeps(
                    package=package,
                    build_dep_specifiers=deps,
                    resolved_versions=resolved,
                )

                for dep_name, dep_version in resolved.items():
                    pv = PackageVersion(name=dep_name, version=dep_version)
                    if pv.key not in all_known:
                        all_known[pv.key] = pv
                        next_pending.append(pv)

            pending = next_pending

    if not all_resolved:
        logger.info("No build dependencies found")
        return

    # Step 3: Group compatible packages
    groups = group_packages(list(all_resolved.values()))
    logger.info("Grouped into %d requirement sets", len(groups))

    # Step 4: Write output files
    for i, group in enumerate(groups):
        suffix = "" if i == 0 else f"-{i}"
        in_file = output_dir / f"requirements-build{suffix}.in"
        txt_file = output_dir / f"requirements-build{suffix}.txt"

        merged = merge_specifiers(group)
        source_packages = [dep.package for dep in group]
        ann = build_annotations(group) if annotate_requirements else None
        write_in_file(in_file, merged, source_packages=source_packages, annotations=ann)
        logger.info("Wrote %s (%d requirements)", in_file, len(merged))

        uv_pip_compile(
            in_file,
            txt_file,
            generate_hashes=True,
            exclude_newer=exclude_newer,
        )
        logger.info("Compiled %s", txt_file)

    # Step 5: Clean up stale files from prior runs
    n_groups = len(groups)
    i = n_groups
    while True:
        suffix = f"-{i}"
        in_file = output_dir / f"requirements-build{suffix}.in"
        txt_file = output_dir / f"requirements-build{suffix}.txt"
        if not in_file.exists() and not txt_file.exists():
            break
        if in_file.exists():
            in_file.unlink()
            logger.info("Removed stale %s", in_file)
        if txt_file.exists():
            txt_file.unlink()
            logger.info("Removed stale %s", txt_file)
        i += 1
