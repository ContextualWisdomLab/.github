"""The coverage tool image must count root-reserved blocks for apt archives."""

from pathlib import Path

import yaml


def test_coverage_tool_image_apt_uses_root_reserved_space() -> None:
    """apt must not reject the coverage image fetch using only f_bavail."""

    workflow = yaml.safe_load(
        Path(".github/workflows/opencode-review-dispatch.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["coverage-evidence"]["steps"]
    script = next(
        step["run"]
        for step in steps
        if step.get("name") == "Measure test and docstring evidence"
    )
    dockerfile = script.split("cat >\"$coverage_build_dir/Dockerfile\" <<'DOCKERFILE'\n", 1)[1]
    dockerfile = dockerfile.split("\n          DOCKERFILE\n", 1)[0]
    apt_layer = dockerfile.split("COPY coverage-cargo-fixtures", 1)[0]
    sandbox = apt_layer.index('APT::Sandbox::User "";')
    install = apt_layer.index("apt-get install --no-install-recommends -y")
    assert sandbox < install
    assert 'APT::Keep-Downloaded-Packages "false";' in apt_layer
    assert "rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*" in apt_layer
    assert "rm -f /etc/apt/apt.conf.d/99-opencode-coverage-apt-disk" in apt_layer
    for package_name in (
        "ca-certificates",
        "cargo",
        "llvm-19",
        "r-base",
        "r-cran-covr",
        "r-cran-testthat",
        "rustc",
        "xz-utils",
    ):
        assert f"    {package_name} \\" in apt_layer
