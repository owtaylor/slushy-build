from dataclasses import dataclass
from pathlib import Path
import re

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


@dataclass(frozen=True)
class PackageVersion:
    name: str
    version: str

    @property
    def key(self) -> str:
        return f"{self.name}-{self.version}"


def filter_requirements(text: str) -> str:
    """Remove requirements with non-matching platform markers, preserving formatting."""
    raw_lines = text.splitlines(keepends=True)
    result: list[str] = []
    i = 0
    while i < len(raw_lines):
        start = i
        joined = raw_lines[i]
        while joined.rstrip("\n").endswith("\\") and i + 1 < len(raw_lines):
            i += 1
            joined += raw_lines[i]
        i += 1

        stripped = joined.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("--"):
            result.extend(raw_lines[start:i])
            continue

        cleaned = re.sub(r"\s*\\$", "", stripped, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*--hash=\S+", "", cleaned).strip()
        try:
            req = Requirement(cleaned)
        except Exception:
            result.extend(raw_lines[start:i])
            continue

        if req.marker is not None and not req.marker.evaluate():
            continue

        result.extend(raw_lines[start:i])

    return "".join(result)


def parse_requirements(text: str) -> list[PackageVersion]:
    """Parse a requirements.txt into a list of pinned package versions.

    Handles comments, blank lines, hash lines, markers, extras,
    and backslash continuations.
    """
    lines = _join_continuations(text.splitlines())
    result = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        line = re.sub(r"\s*\\$", "", line)
        line = re.sub(r"\s*--hash=\S+", "", line)
        line = line.strip()
        if not line:
            continue
        try:
            req = Requirement(line)
        except Exception:
            continue
        if req.marker is not None and not req.marker.evaluate():
            continue
        version = None
        for spec in req.specifier:
            if spec.operator == "==":
                version = spec.version
                break
        if version is None:
            continue
        result.append(
            PackageVersion(
                name=canonicalize_name(req.name),
                version=version,
            )
        )
    return result


def parse_resolved_requirements(text: str) -> dict[str, str]:
    """Parse uv pip compile output into {canonical_name: version}."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"\s*;.*", "", line)
        line = re.sub(r"\s*\\$", "", line)
        line = re.sub(r"\s*--hash=\S+", "", line)
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([a-zA-Z0-9_.-]+(?:\[[^\]]+\])?)\s*==\s*(.+)$", line)
        if m:
            name = re.sub(r"\[.*\]", "", m.group(1))
            result[canonicalize_name(name)] = m.group(2).strip()
    return result


def apply_constraints(deps: list[str], constraints: list[str]) -> list[str]:
    """Augment build dep specifiers with extra constraints.

    For each dep whose canonical name matches a constraint, the constraint's
    specifiers are appended (e.g. "uv-build>=0.6.1" + constraint "uv-build<0.11.8"
    becomes "uv-build<0.11.8,>=0.6.1").
    """
    if not constraints:
        return deps

    constraint_map: dict[str, Requirement] = {}
    for c in constraints:
        req = Requirement(c)
        constraint_map[canonicalize_name(req.name)] = req

    result = []
    for dep_str in deps:
        dep_str = dep_str.strip()
        if not dep_str:
            result.append(dep_str)
            continue
        try:
            req = Requirement(dep_str)
        except Exception:
            result.append(dep_str)
            continue
        canonical = canonicalize_name(req.name)
        if canonical in constraint_map:
            req.specifier &= constraint_map[canonical].specifier
        result.append(str(req))
    return result


SOURCE_COMMENT_PREFIX = "# slushy-build-source: "


def write_in_file(
    path: Path,
    requirements: list[str],
    source_packages: list[PackageVersion] | None = None,
    annotations: dict[str, list[str]] | None = None,
) -> None:
    lines: list[str] = []
    if source_packages:
        for pkg in sorted(source_packages, key=lambda p: p.key):
            lines.append(f"{SOURCE_COMMENT_PREFIX}{pkg.name}=={pkg.version}")
    for req_str in requirements:
        if annotations:
            req_str_stripped = req_str.strip()
            if req_str_stripped:
                try:
                    req = Requirement(req_str_stripped)
                    canonical = canonicalize_name(req.name)
                    for ann in annotations.get(canonical, []):
                        lines.append(f"# {ann}")
                except Exception:
                    pass
        lines.append(req_str)
    path.write_text("\n".join(lines) + "\n")


def parse_in_file_sources(path: Path) -> list[tuple[str, str]]:
    """Extract (name, version) pairs from slushy-build-source comments in a .in file."""
    result = []
    for line in path.read_text().splitlines():
        if line.startswith(SOURCE_COMMENT_PREFIX):
            spec = line[len(SOURCE_COMMENT_PREFIX) :].strip()
            if "==" in spec:
                name, version = spec.split("==", 1)
                result.append((canonicalize_name(name), version))
    return result


def _join_continuations(lines: list[str]) -> list[str]:
    result = []
    current = ""
    for line in lines:
        if current:
            current += " " + line.strip()
        else:
            current = line
        if not current.rstrip().endswith("\\"):
            result.append(current)
            current = ""
        else:
            current = current.rstrip()[:-1]
    if current:
        result.append(current)
    return result
