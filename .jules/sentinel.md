## 2024-05-24 - CI Dependency Missing and Fix
**Learning:** CI workflow `.github/workflows/repository-metadata-reconcile.yml` was missing `defusedxml` which is necessary to run the `noema-document-ci` script when validate is tested.
**Prevention:** Make sure all dependencies are imported when using `--require-hashes`.
