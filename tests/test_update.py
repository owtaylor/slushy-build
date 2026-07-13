from slushy_build.update import run_update


class TestRunUpdate:
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
