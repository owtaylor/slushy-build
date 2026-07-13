from slushy_build.grouping import (
    ResolvedPackageDeps,
    are_compatible,
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


class TestMergeSpecifiers:
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
