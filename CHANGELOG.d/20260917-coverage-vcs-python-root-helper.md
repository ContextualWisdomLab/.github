### Coverage image VCS import-root resolver is executable and contract-proven

- #2123 already admitted immutable `python/<import>` layouts so the trusted coverage
  tool image no longer dies at docker step #17 on `fast-mlsirm@09f762ded`
  (`python/fast_mlsirm`). The #2157 follow-up extracts that exact admission logic into
  `scripts/ci/resolve_opencode_base_vcs_import_root.sh`, which
  `opencode-review-dispatch.yml` installs into the coverage build context and the
  Dockerfile `COPY`s/executes — so candidate discovery cannot silently drift inside an
  untested HEREDOC. `tests/test_opencode_vcs_python_source_root_contract.py` proves
  `python/` package and single-module layouts resolve, `src/` and repository-root
  layouts still resolve, and missing/ambiguous/namespace/compiled trees still fail
  closed with the historical diagnostics. Doctoring
  `docs/doctoring/opencode-vcs-python-source-root.md` and gap
  `CONTROL-OPENCODE-VCS-PYROOT-01` record #2123 supersession; issue #2157 stays open
  until a consumer `coverage-evidence` job past step #17 is linked. Refs #2157, #2123.
