from itertools import permutations
import os
import subprocess
import sys
import textwrap

from slushy_build.grouping import (
    ResolvedPackageDeps,
    are_compatible,
    build_annotations,
    find_best_clique,
    group_packages,
    merge_specifiers,
)
from slushy_build.requirements import PackageVersion


def _make_pkg(name, version, specifiers, resolved):
    return ResolvedPackageDeps(
        package=PackageVersion(name, version),
        build_dep_specifiers=specifiers,
        resolved_versions=resolved,
    )


class TestAreCompatible:
    def test_compatible_disjoint(self):
        a = _make_pkg("a", "1.0", [], {"setuptools": "83.0.0"})
        b = _make_pkg("b", "1.0", [], {"wheel": "0.41.0"})
        assert are_compatible(a, b)

    def test_compatible_same_version(self):
        a = _make_pkg("a", "1.0", [], {"setuptools": "83.0.0"})
        b = _make_pkg("b", "1.0", [], {"setuptools": "83.0.0"})
        assert are_compatible(a, b)

    def test_incompatible(self):
        a = _make_pkg("a", "1.0", [], {"setuptools": "83.0.0"})
        b = _make_pkg("b", "1.0", [], {"setuptools": "82.0.1"})
        assert not are_compatible(a, b)


class TestFindBestClique:
    def test_tiebreak_version_tradeoff(self):
        pkgs = [
            _make_pkg("a", "1", [], {"x": "2", "y": "1"}),
            _make_pkg("b", "1", [], {"x": "2", "y": "1"}),
            _make_pkg("c", "1", [], {"x": "1", "y": "2"}),
            _make_pkg("d", "1", [], {"x": "1", "y": "2"}),
        ]
        for order in permutations(pkgs):
            assert [p.package.name for p in find_best_clique(list(order))] == ["a", "b"]

    def test_tiebreak_equal_scores(self):
        # Compatibility compares exact strings, while version scores treat
        # 1 and 1.0 as equal. Member keys must break the resulting tie.
        pkgs = [
            _make_pkg("a", "1", [], {"x": "1"}),
            _make_pkg("b", "1", [], {"x": "1.0"}),
            _make_pkg("common", "1", [], {}),
        ]
        for order in permutations(pkgs):
            assert [p.package.name for p in find_best_clique(list(order))] == ["a", "common"]

    def test_tiebreak_missing_dependency(self):
        pkgs = [
            _make_pkg("a", "1", [], {"x": "1"}),
            _make_pkg("b", "1", [], {"x": "1"}),
            _make_pkg("c", "1", [], {"x": "2", "y": "1"}),
            _make_pkg("d", "1", [], {"x": "2", "y": "1"}),
        ]
        assert [p.package.name for p in find_best_clique(pkgs)] == ["c", "d"]

    def test_single_package(self):
        p = _make_pkg("a", "1.0", [], {"setuptools": "83.0.0"})
        result = find_best_clique([p])
        assert len(result) == 1
        assert result[0].package.key == "a-1.0"

    def test_all_compatible(self):
        pkgs = [
            _make_pkg("a", "1.0", [], {"setuptools": "83.0.0"}),
            _make_pkg("b", "1.0", [], {"setuptools": "83.0.0", "wheel": "0.41.0"}),
            _make_pkg("c", "1.0", [], {"wheel": "0.41.0"}),
        ]
        result = find_best_clique(pkgs)
        assert len(result) == 3

    def test_two_groups(self):
        pkgs = [
            _make_pkg("a", "1.0", [], {"setuptools": "83.0.0"}),
            _make_pkg("b", "1.0", [], {"setuptools": "83.0.0"}),
            _make_pkg("c", "1.0", [], {"setuptools": "82.0.1"}),
        ]
        result = find_best_clique(pkgs)
        assert len(result) == 2
        keys = {p.package.key for p in result}
        assert keys == {"a-1.0", "b-1.0"}

    def test_no_edges_returns_first(self):
        pkgs = [
            _make_pkg("a", "1.0", [], {"x": "1"}),
            _make_pkg("b", "1.0", [], {"x": "2"}),
            _make_pkg("c", "1.0", [], {"x": "3"}),
        ]
        result = find_best_clique(pkgs)
        assert len(result) == 1
        assert result[0].package.key == "a-1.0"

    def test_tiebreak_newest(self):
        # Two cliques of size 2, should pick the one with newer versions
        pkgs = [
            _make_pkg("a", "1.0", [], {"setuptools": "83.0.0", "wheel": "0.41.0"}),
            _make_pkg("b", "1.0", [], {"setuptools": "83.0.0", "wheel": "0.41.0"}),
            _make_pkg("c", "1.0", [], {"setuptools": "82.0.1", "wheel": "0.40.0"}),
            _make_pkg("d", "1.0", [], {"setuptools": "82.0.1", "wheel": "0.40.0"}),
        ]
        result = find_best_clique(pkgs)
        keys = {p.package.key for p in result}
        assert keys == {"a-1.0", "b-1.0"}


class TestBuildAnnotations:
    def test_single_package(self):
        pkgs = [_make_pkg("requests", "2.31.0", ["setuptools>=67.0", "wheel"], {})]
        result = build_annotations(pkgs)
        assert result == {
            "setuptools": ["requests==2.31.0: setuptools>=67.0"],
            "wheel": ["requests==2.31.0: wheel"],
        }

    def test_multiple_packages(self):
        pkgs = [
            _make_pkg("requests", "2.31.0", ["setuptools>=67.0"], {}),
            _make_pkg("urllib3", "2.0.4", ["setuptools>=60.0"], {}),
        ]
        result = build_annotations(pkgs)
        assert result["setuptools"] == [
            "requests==2.31.0: setuptools>=67.0",
            "urllib3==2.0.4: setuptools>=60.0",
        ]

    def test_skips_non_matching_markers(self):
        pkgs = [
            _make_pkg("a", "1.0", ['setuptools>=67.0 ; sys_platform == "win32"'], {}),
        ]
        result = build_annotations(pkgs)
        assert result == {}


class TestMergeSpecifiers:
    def test_equivalent_spellings(self):
        pkgs = [
            _make_pkg("a", "1", ["maturin>=1.15.0,<2", "wheel!=1.0"], {}),
            _make_pkg("b", "1", ["maturin>=1.15,<2.0", "wheel!=1"], {}),
        ]
        for order in permutations(pkgs):
            assert merge_specifiers(list(order)) == ["maturin<2,>=1.15.0", "wheel!=1"]

    def test_basic(self):
        pkgs = [
            _make_pkg("a", "1.0", ["setuptools>=67.0"], {}),
        ]
        result = merge_specifiers(pkgs)
        assert "setuptools>=67" in result[0] or "setuptools>=67.0" in result[0]

    def test_intersection(self):
        pkgs = [
            _make_pkg("a", "1.0", ["setuptools>=67.0"], {}),
            _make_pkg("b", "1.0", ["setuptools>=69.0,<80"], {}),
        ]
        result = merge_specifiers(pkgs)
        assert len(result) == 1
        assert ">=69" in result[0]
        assert "<80" in result[0]

    def test_extras_merged(self):
        pkgs = [
            _make_pkg("a", "1.0", ["setuptools-scm[toml]>=8.0"], {}),
            _make_pkg("b", "1.0", ["setuptools-scm>=7.0"], {}),
        ]
        result = merge_specifiers(pkgs)
        assert len(result) == 1
        assert "toml" in result[0]
        assert ">=8" in result[0]

    def test_multiple_packages(self):
        pkgs = [
            _make_pkg("a", "1.0", ["setuptools>=67.0", "wheel"], {}),
            _make_pkg("b", "1.0", ["setuptools>=69.0"], {}),
        ]
        result = merge_specifiers(pkgs)
        names = [r.split("[")[0].split(">")[0].split("<")[0].split("!")[0].split("=")[0].strip() for r in result]
        assert "setuptools" in names
        assert "wheel" in names


class TestGroupPackages:
    def test_stable_across_hash_seeds(self):
        script = textwrap.dedent("""\
            import json
            from slushy_build.grouping import ResolvedPackageDeps, group_packages, merge_specifiers
            from slushy_build.requirements import PackageVersion

            packages = [
                ResolvedPackageDeps(PackageVersion("a", "1"), ["maturin>=1.15.0,<2"], {"x": "2", "y": "1"}),
                ResolvedPackageDeps(PackageVersion("b", "1"), ["maturin>=1.15,<2.0"], {"x": "2", "y": "1"}),
                ResolvedPackageDeps(PackageVersion("c", "1"), [], {"x": "1", "y": "2"}),
                ResolvedPackageDeps(PackageVersion("d", "1"), [], {"x": "1", "y": "2"}),
            ]
            print(json.dumps([
                ([p.package.name for p in group], merge_specifiers(group))
                for group in group_packages(packages)
            ]))
        """)
        outputs = {
            subprocess.check_output(
                [sys.executable, "-c", script],
                env={**os.environ, "PYTHONHASHSEED": str(seed)},
                text=True,
            ).strip()
            for seed in range(8)
        }
        assert outputs == {'[[["a", "b"], ["maturin<2,>=1.15.0"]], [["c", "d"], []]]'}

    def test_single_group(self):
        pkgs = [
            _make_pkg("a", "1.0", ["setuptools>=67"], {"setuptools": "83.0.0"}),
            _make_pkg("b", "1.0", ["wheel"], {"wheel": "0.41.0"}),
        ]
        groups = group_packages(pkgs)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_multiple_groups(self):
        pkgs = [
            _make_pkg("a", "1.0", ["setuptools>=67"], {"setuptools": "83.0.0"}),
            _make_pkg("b", "1.0", ["setuptools>=67"], {"setuptools": "82.0.1"}),
        ]
        groups = group_packages(pkgs)
        assert len(groups) == 2
        assert len(groups[0]) == 1
        assert len(groups[1]) == 1

    def test_exhaustive(self):
        pkgs = [
            _make_pkg("a", "1.0", [], {"setuptools": "83.0.0"}),
            _make_pkg("b", "1.0", [], {"setuptools": "83.0.0"}),
            _make_pkg("c", "1.0", [], {"setuptools": "82.0.1"}),
            _make_pkg("d", "1.0", [], {"setuptools": "82.0.1"}),
        ]
        groups = group_packages(pkgs)
        all_keys = set()
        for g in groups:
            for p in g:
                all_keys.add(p.package.key)
        assert all_keys == {"a-1.0", "b-1.0", "c-1.0", "d-1.0"}
