"""Official build-tool assets must match reviewed bytes and native links."""

import hashlib
import io
import tarfile
import zipfile

import pytest

from scripts.ci import verify_release_maturin_tool_assets as verifier


def test_maturin_asset_review_rejects_changed_bytes_and_unknown_links(monkeypatch):
    archives = {}
    assets = {}
    names = {
        "aarch64-unknown-linux-gnu": "maturin-aarch64-unknown-linux-musl.tar.gz",
        "x86_64-unknown-linux-gnu": "maturin-x86_64-unknown-linux-musl.tar.gz",
        "universal2-apple-darwin/ARM64": "maturin-aarch64-apple-darwin.tar.gz",
        "universal2-apple-darwin/X64": "maturin-x86_64-apple-darwin.tar.gz",
        "x86_64-pc-windows-msvc": "maturin-x86_64-pc-windows-msvc.zip",
    }
    for key, filename in names.items():
        binary = key.encode()
        buffer = io.BytesIO()
        if filename.endswith(".zip"):
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("maturin.exe", binary)
        else:
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                member = tarfile.TarInfo("maturin")
                member.size = len(binary)
                archive.addfile(member, io.BytesIO(binary))
        archives[filename] = buffer.getvalue()
        arch = "aarch64" if "aarch64" in key or key.endswith("/ARM64") else "x86_64"
        needed = (["kernel32.dll"] if "windows" in key else
                  ["/usr/lib/libSystem.B.dylib"] if "darwin" in key else [])
        assets[key] = {"asset_filename": filename,
                       "asset_sha256": hashlib.sha256(archives[filename]).hexdigest(),
                       "binary_sha256": hashlib.sha256(binary).hexdigest(),
                       "native_links": [{"arch": arch, "needed": needed}]}
    evidence = {"schema": "cwl.release-maturin-tool/1", "tag": "v1.15.0",
                "assets": assets}

    def links(binary, target, reader, *, allow_subset):
        key = binary.decode()
        return [{"arch": assets[key]["native_links"][0]["arch"],
                 "needed": assets[key]["native_links"][0]["needed"]}]

    monkeypatch.setattr(verifier, "_links", links)
    verifier.verify_assets(evidence, "/reader", lambda name: archives[name])
    changed = dict(archives)
    changed[names["x86_64-pc-windows-msvc"]] = b"changed"
    with pytest.raises(ValueError, match="asset bytes differ"):
        verifier.verify_assets(evidence, "/reader", lambda name: changed[name])
    monkeypatch.setattr(verifier, "_links", lambda *args, **kwargs: [
        {"arch": "x86_64", "needed": ["foreign.dll"]}])
    with pytest.raises(ValueError, match="native links differ|unreviewed"):
        verifier.verify_assets(evidence, "/reader", lambda name: archives[name])
