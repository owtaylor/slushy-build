from collections import defaultdict
from dataclasses import dataclass

import networkx as nx
from packaging.requirements import Requirement
from packaging.specifiers import Specifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import parse as parse_version

from .requirements import PackageVersion


@dataclass
class ResolvedPackageDeps:
    package: PackageVersion
    build_dep_specifiers: list[str]
    resolved_versions: dict[str, str]


def are_compatible(a: ResolvedPackageDeps, b: ResolvedPackageDeps) -> bool:
    for k, v in a.resolved_versions.items():
        if k in b.resolved_versions and b.resolved_versions[k] != v:
            return False
    return True


def find_best_clique(
    packages: list[ResolvedPackageDeps],
) -> list[ResolvedPackageDeps]:
    packages = sorted(packages, key=lambda p: p.package.key)
    if len(packages) == 1:
        return packages

    G = nx.Graph()
    for i, p1 in enumerate(packages):
        for p2 in packages[i + 1 :]:
            if are_compatible(p1, p2):
                G.add_edge(p1.package.key, p2.package.key)

    by_key = {p.package.key: p for p in packages}

    if G.number_of_edges() == 0:
        return [packages[0]]

    cliques = list(nx.find_cliques(G))
    max_len = max(len(c) for c in cliques)
    # NetworkX traverses sets internally. Stabilize both member order and the
    # final fallback when equally large cliques have equal version scores.
    cliques = sorted(sorted(c) for c in cliques if len(c) == max_len)

    if len(cliques) == 1:
        return [by_key[k] for k in cliques[0]]

    # Tiebreak: prefer newest versions among the "troublesome" packages
    # (those that differ between tied cliques)
    common = set(cliques[0])
    for c in cliques[1:]:
        common &= set(c)

    troublesome = set()
    for c in cliques:
        troublesome |= set(c) - common

    def clique_to_versions(clique):
        result = {}
        for k in clique:
            if k in troublesome:
                result |= by_key[k].resolved_versions
        return result

    fallback_versions = {}
    for clique in reversed(cliques):
        for k in clique:
            fallback_versions |= by_key[k].resolved_versions

    versions = [clique_to_versions(c) for c in cliques]

    all_packages = set()
    for v in versions:
        all_packages |= set(v.keys())

    # Compare the same dependency first in every process when version tradeoffs
    # exist (one clique has newer X while another has newer Y).
    package_names = sorted(all_packages)

    def versions_to_sort_key(v):
        return [parse_version(v.get(p, fallback_versions[p])) for p in package_names]

    sort_keys = [versions_to_sort_key(v) for v in versions]
    best_index = max(range(len(cliques)), key=lambda i: sort_keys[i])
    return [by_key[k] for k in cliques[best_index]]


def build_annotations(packages: list[ResolvedPackageDeps]) -> dict[str, list[str]]:
    """Map each canonical requirement name to provenance annotations."""
    result: defaultdict[str, list[str]] = defaultdict(list)
    for pkg in sorted(packages, key=lambda p: p.package.key):
        for spec_str in pkg.build_dep_specifiers:
            spec_str = spec_str.strip()
            if not spec_str:
                continue
            req = Requirement(spec_str)
            if req.marker is not None and not req.marker.evaluate():
                continue
            canonical = canonicalize_name(req.name)
            result[canonical].append(f"{pkg.package.name}=={pkg.package.version}: {spec_str}")
    return dict(result)


def merge_specifiers(packages: list[ResolvedPackageDeps]) -> list[str]:
    """Merge build dep specifiers from multiple packages into a combined list."""
    all_reqs: defaultdict[str, list[Requirement]] = defaultdict(list)
    for pkg in packages:
        for spec_str in pkg.build_dep_specifiers:
            spec_str = spec_str.strip()
            if not spec_str:
                continue
            req = Requirement(spec_str)
            if req.marker is not None:
                if not req.marker.evaluate():
                    continue
                req.marker = None
            canonical = canonicalize_name(req.name)
            all_reqs[canonical].append(req)

    result = []
    for package_name in sorted(all_reqs.keys()):
        # Sort so the bound-selection loop below consistently retains the same
        # spelling when equivalent bounds such as <2 and <2.0 are present.
        specifiers = sorted(
            (s for r in all_reqs[package_name] for s in r.specifier),
            key=str,
        )

        upper_bound: Specifier | None = None
        lower_bound: Specifier | None = None
        other: list[Specifier] = []

        for specifier in specifiers:
            if specifier.operator in ("<", "<="):
                if upper_bound is None or upper_bound.contains(specifier.version):
                    upper_bound = specifier
            elif specifier.operator in (">", ">="):
                if lower_bound is None or lower_bound.contains(specifier.version):
                    lower_bound = specifier
            else:
                other.append(specifier)

        other = [
            s
            for s in other
            if not (
                s.operator == "!="
                and (
                    (lower_bound and not lower_bound.contains(s.version))
                    or (upper_bound and not upper_bound.contains(s.version))
                )
            )
        ]

        all_specifiers: list[Specifier] = []
        if lower_bound:
            all_specifiers.append(lower_bound)
        if upper_bound:
            all_specifiers.append(upper_bound)
        all_specifiers += other

        extras: set[str] = set()
        for req in all_reqs[package_name]:
            extras |= req.extras

        merged = Requirement(package_name)
        merged.specifier = SpecifierSet(specifiers=all_specifiers)
        merged.extras = extras
        result.append(str(merged))

    return result


def group_packages(
    all_deps: list[ResolvedPackageDeps],
) -> list[list[ResolvedPackageDeps]]:
    """Partition packages into groups of mutually compatible packages."""
    remaining = sorted(all_deps, key=lambda d: d.package.key)
    groups = []
    while remaining:
        best = find_best_clique(remaining)
        groups.append(best)
        best_keys = {p.package.key for p in best}
        remaining = [p for p in remaining if p.package.key not in best_keys]
    return groups
