import json
from zipfile import ZipFile

from slushy_build.requirements import parse_resolved_requirements
from slushy_build.update import run_update


def _minimal_pipelinerun(prefetch_value: str) -> str:
    return (
        "apiVersion: tekton.dev/v1\n"
        "kind: PipelineRun\n"
        "metadata:\n"
        "  name: example-pr\n"
        "spec:\n"
        "  params:\n"
        "    - name: prefetch-input\n"
        f"      value: '{prefetch_value}'\n"
    )


class TestRunUpdate:
    def test_from_scratch_then_incremental_is_stable(self, mocker, monkeypatch, tmp_path):
        # Use real uv resolution against local wheels: no network or index drift.
        wheels = tmp_path / "wheels"
        wheels.mkdir()
        for name, version, deps in [
            ("builder", "1", ["helper"]),
            ("builder", "2", []),
            ("helper", "1", []),
            ("backend", "1", []),
        ]:
            with ZipFile(wheels / f"{name}-{version}-py3-none-any.whl", "w") as wheel:
                info = f"{name}-{version}.dist-info"
                wheel.writestr(
                    f"{info}/METADATA",
                    f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
                    + "".join(f"Requires-Dist: {dep}\n" for dep in deps),
                )
                wheel.writestr(
                    f"{info}/WHEEL",
                    "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
                )
                wheel.writestr(f"{info}/RECORD", "")

        monkeypatch.setenv("UV_NO_INDEX", "true")
        monkeypatch.setenv("UV_FIND_LINKS", str(wheels))
        monkeypatch.setenv("UV_OFFLINE", "true")
        monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "cache"))
        mocker.patch(
            "slushy_build.update.build_deps_mod.get_build_dependencies",
            side_effect=lambda pkg: {
                "app-1": ["builder"],
                "builder-2": ["backend"],
            }.get(pkg.key, []),
        )
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("app==1\n")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "requirements-build.in").write_text("# slushy-build-source: app==1\nbuilder\n")
        txt_file = output_dir / "requirements-build.txt"
        txt_file.write_text("builder==1\nhelper==1\n")

        def update(from_scratch):
            run_update(
                uv_lock=False,
                requirements_file=req_file,
                from_scratch=from_scratch,
                exclude_newer=None,
                output_dir=output_dir,
                update_pipeline=False,
            )
            return {p.name: p.read_bytes() for p in output_dir.iterdir()}

        # Incremental updates preserve the compatible old builder pin.
        update(False)
        assert parse_resolved_requirements(txt_file.read_text()) == {"builder": "1", "helper": "1"}
        fresh_output = update(True)
        assert parse_resolved_requirements(txt_file.read_text()) == {"builder": "2", "backend": "1"}
        assert b"# slushy-build-source: builder==2\n" in fresh_output["requirements-build.in"]
        assert update(False) == fresh_output

    def test_from_requirements_file(self, mocker, tmp_path):
        req_file = tmp_path / "reqs.txt"
        req_file.write_text("requests==2.31.0\nurllib3==2.0.4\n")
        output_dir = tmp_path / "output"

        mocker.patch(
            "slushy_build.update.build_deps_mod.get_build_dependencies",
            side_effect=lambda pkg: {
                "requests-2.31.0": ["setuptools>=67.0"],
                "urllib3-2.0.4": ["setuptools>=67.0"],
            }.get(pkg.key, []),
        )
        mocker.patch(
            "slushy_build.update.resolve_build_deps",
            side_effect=lambda pkg, deps, work_dir, exclude_newer=None, **kwargs: {
                "requests-2.31.0": {"setuptools": "83.0.0"},
                "urllib3-2.0.4": {"setuptools": "83.0.0"},
            }.get(pkg.key, {}),
        )

        def fake_final_compile(in_file, txt_file, **kwargs):
            txt_file.write_text("setuptools==83.0.0\n")

        mocker.patch("slushy_build.update.uv_pip_compile", side_effect=fake_final_compile)

        run_update(
            uv_lock=False,
            requirements_file=req_file,
            from_scratch=False,
            exclude_newer=None,
            output_dir=output_dir,
        )

        assert (output_dir / "requirements-build.in").exists()
        assert (output_dir / "requirements-build.txt").exists()

    def test_from_uv_lock(self, mocker, tmp_path):
        mocker.patch("slushy_build.update.uv_export", return_value="requests==2.31.0\n")
        mocker.patch(
            "slushy_build.update.build_deps_mod.get_build_dependencies",
            return_value=["setuptools>=67.0"],
        )
        mocker.patch(
            "slushy_build.update.resolve_build_deps",
            return_value={"setuptools": "83.0.0"},
        )

        def fake_compile(in_file, txt_file, **kwargs):
            txt_file.write_text("setuptools==83.0.0\n")

        mocker.patch("slushy_build.update.uv_pip_compile", side_effect=fake_compile)

        output_dir = tmp_path / "output"
        run_update(
            uv_lock=True,
            requirements_file=None,
            from_scratch=False,
            exclude_newer=None,
            output_dir=output_dir,
        )

        assert (output_dir / "requirements.txt").exists()
        assert (output_dir / "requirements-build.in").exists()

    def test_iterative_discovery(self, mocker, tmp_path):
        """Build deps of package A introduce package C, which also has deps."""
        req_file = tmp_path / "reqs.txt"
        req_file.write_text("a==1.0\n")
        output_dir = tmp_path / "output"

        mock_get_deps = mocker.patch(
            "slushy_build.update.build_deps_mod.get_build_dependencies",
            side_effect=lambda pkg: {
                "a-1.0": ["setuptools>=67.0"],
                "setuptools-83.0.0": ["wheel"],
            }.get(pkg.key, []),
        )
        mocker.patch(
            "slushy_build.update.resolve_build_deps",
            side_effect=lambda pkg, deps, work_dir, exclude_newer=None, **kwargs: {
                "a-1.0": {"setuptools": "83.0.0"},
                "setuptools-83.0.0": {"wheel": "0.41.0"},
            }.get(pkg.key, {}),
        )

        def fake_compile(in_file, txt_file, **kwargs):
            txt_file.write_text("setuptools==83.0.0\nwheel==0.41.0\n")

        mocker.patch("slushy_build.update.uv_pip_compile", side_effect=fake_compile)

        run_update(
            uv_lock=False,
            requirements_file=req_file,
            from_scratch=False,
            exclude_newer=None,
            output_dir=output_dir,
        )

        assert mock_get_deps.call_count >= 2

    def test_writes_source_comments(self, mocker, tmp_path):
        req_file = tmp_path / "reqs.txt"
        req_file.write_text("requests==2.31.0\n")
        output_dir = tmp_path / "output"

        mocker.patch(
            "slushy_build.update.build_deps_mod.get_build_dependencies",
            return_value=["setuptools>=67.0"],
        )
        mocker.patch(
            "slushy_build.update.resolve_build_deps",
            return_value={"setuptools": "83.0.0"},
        )

        def fake_compile(in_file, txt_file, **kwargs):
            txt_file.write_text("setuptools==83.0.0\n")

        mocker.patch("slushy_build.update.uv_pip_compile", side_effect=fake_compile)

        run_update(
            uv_lock=False,
            requirements_file=req_file,
            from_scratch=False,
            exclude_newer=None,
            output_dir=output_dir,
        )

        in_content = (output_dir / "requirements-build.in").read_text()
        assert "# slushy-build-source: requests==2.31.0" in in_content

    def test_incremental_passes_seed(self, mocker, tmp_path):
        req_file = tmp_path / "reqs.txt"
        req_file.write_text("requests==2.31.0\n")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "requirements-build.in").write_text("# slushy-build-source: requests==2.30.0\nsetuptools>=67.0\n")
        (output_dir / "requirements-build.txt").write_text("setuptools==82.0.0\n")

        mocker.patch(
            "slushy_build.update.build_deps_mod.get_build_dependencies",
            return_value=["setuptools>=67.0"],
        )
        mock_resolve = mocker.patch(
            "slushy_build.update.resolve_build_deps",
            return_value={"setuptools": "83.0.0"},
        )

        def fake_compile(in_file, txt_file, **kwargs):
            txt_file.write_text("setuptools==83.0.0\n")

        mocker.patch("slushy_build.update.uv_pip_compile", side_effect=fake_compile)

        run_update(
            uv_lock=False,
            requirements_file=req_file,
            from_scratch=False,
            exclude_newer=None,
            output_dir=output_dir,
        )

        _, kwargs = mock_resolve.call_args
        assert kwargs["seed_content"] == "setuptools==82.0.0\n"

    def test_from_scratch_skips_seed(self, mocker, tmp_path):
        req_file = tmp_path / "reqs.txt"
        req_file.write_text("requests==2.31.0\n")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "requirements-build.in").write_text("# slushy-build-source: requests==2.31.0\nsetuptools>=67.0\n")
        (output_dir / "requirements-build.txt").write_text("setuptools==82.0.0\n")

        mocker.patch(
            "slushy_build.update.build_deps_mod.get_build_dependencies",
            return_value=["setuptools>=67.0"],
        )
        mock_resolve = mocker.patch(
            "slushy_build.update.resolve_build_deps",
            return_value={"setuptools": "83.0.0"},
        )

        def fake_compile(in_file, txt_file, **kwargs):
            txt_file.write_text("setuptools==83.0.0\n")

        mocker.patch("slushy_build.update.uv_pip_compile", side_effect=fake_compile)

        run_update(
            uv_lock=False,
            requirements_file=req_file,
            from_scratch=True,
            exclude_newer=None,
            output_dir=output_dir,
        )

        _, kwargs = mock_resolve.call_args
        assert kwargs["seed_content"] is None

    def test_stale_files_cleaned(self, mocker, tmp_path):
        req_file = tmp_path / "reqs.txt"
        req_file.write_text("a==1.0\n")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Simulate a prior run that produced 2 groups
        (output_dir / "requirements-build-1.in").write_text("old")
        (output_dir / "requirements-build-1.txt").write_text("old")

        mocker.patch(
            "slushy_build.update.build_deps_mod.get_build_dependencies",
            return_value=["setuptools>=67.0"],
        )
        mocker.patch(
            "slushy_build.update.resolve_build_deps",
            return_value={"setuptools": "83.0.0"},
        )

        def fake_compile(in_file, txt_file, **kwargs):
            txt_file.write_text("setuptools==83.0.0\n")

        mocker.patch("slushy_build.update.uv_pip_compile", side_effect=fake_compile)

        run_update(
            uv_lock=False,
            requirements_file=req_file,
            from_scratch=False,
            exclude_newer=None,
            output_dir=output_dir,
        )

        assert (output_dir / "requirements-build.in").exists()
        assert not (output_dir / "requirements-build-1.in").exists()
        assert not (output_dir / "requirements-build-1.txt").exists()

    def _setup_simple_mocks(self, mocker):
        mocker.patch(
            "slushy_build.update.build_deps_mod.get_build_dependencies",
            return_value=["setuptools>=67.0"],
        )
        mocker.patch(
            "slushy_build.update.resolve_build_deps",
            return_value={"setuptools": "83.0.0"},
        )

        def fake_compile(in_file, txt_file, **kwargs):
            txt_file.write_text("setuptools==83.0.0\n")

        mocker.patch("slushy_build.update.uv_pip_compile", side_effect=fake_compile)

    def test_syncs_pipeline_from_uv_lock(self, mocker, tmp_path):
        mocker.patch("slushy_build.update.uv_export", return_value="requests==2.31.0\n")
        self._setup_simple_mocks(mocker)

        output_dir = tmp_path / ".konflux"
        pipeline_dir = tmp_path / ".tekton"
        pipeline_dir.mkdir()
        value = '[{"type": "pip", "requirements_build_files": ["old.txt"]}, {"type": "rpm", "path": "."}]'
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(_minimal_pipelinerun(value))

        run_update(
            uv_lock=True,
            requirements_file=None,
            from_scratch=False,
            exclude_newer=None,
            output_dir=output_dir,
            pipeline_dir=pipeline_dir,
        )

        entries = json.loads(_prefetch_value(yaml_file.read_text()))
        pip = next(e for e in entries if e["type"] == "pip")
        assert pip["requirements_files"] == [str(output_dir / "requirements.txt")]
        assert pip["requirements_build_files"] == [str(output_dir / "requirements-build.txt")]

    def test_no_update_pipeline_leaves_files_alone(self, mocker, tmp_path):
        """Test existing pipeline is left alone for --no-update-pipeline."""
        mocker.patch("slushy_build.update.uv_export", return_value="requests==2.31.0\n")
        self._setup_simple_mocks(mocker)

        output_dir = tmp_path / ".konflux"
        pipeline_dir = tmp_path / ".tekton"
        pipeline_dir.mkdir()
        value = '[{"type": "pip", "requirements_build_files": ["old.txt"]}]'
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(_minimal_pipelinerun(value))
        original = yaml_file.read_text()

        run_update(
            uv_lock=True,
            requirements_file=None,
            from_scratch=False,
            exclude_newer=None,
            output_dir=output_dir,
            pipeline_dir=pipeline_dir,
            update_pipeline=False,
        )

        assert yaml_file.read_text() == original


def _prefetch_value(text: str) -> str:
    import yaml

    doc = yaml.safe_load(text)
    for param in doc["spec"]["params"]:
        if param["name"] == "prefetch-input":
            return param["value"]
    raise AssertionError("no prefetch-input param")
