"""Official build-tool assets must match reviewed bytes and native links."""

import hashlib
import io
import json
import runpy
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from scripts.ci import verify_release_maturin_tool_assets as verifier


def _asset_case():
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
    return archives, assets, names, evidence


def test_maturin_asset_review_rejects_changed_bytes_and_unknown_links(monkeypatch):
    archives, assets, names, evidence = _asset_case()

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


def test_maturin_asset_review_rejects_incomplete_names_and_executables(monkeypatch):
    archives, assets, _, evidence = _asset_case()
    with pytest.raises(ValueError, match="evidence is incomplete"):
        verifier.verify_assets({**evidence, "tag": "v1.14.0"}, "/reader")

    first_key = next(iter(assets))
    original_name = assets[first_key]["asset_filename"]
    assets[first_key]["asset_filename"] = "foreign.tar.gz"
    with pytest.raises(ValueError, match="asset name is unexpected"):
        verifier.verify_assets(evidence, "/reader")
    assets[first_key]["asset_filename"] = original_name

    monkeypatch.setattr(verifier, "_links", lambda *args, **kwargs: [
        assets[first_key]["native_links"][0]])
    assets[first_key]["binary_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="executable bytes differ"):
        verifier.verify_assets(evidence, "/reader", lambda name: archives[name])


def test_maturin_asset_review_rejects_unreviewed_matching_link(monkeypatch):
    archives, assets, _, evidence = _asset_case()
    first_key = next(iter(assets))
    assets[first_key]["native_links"] = [{"arch": "aarch64", "needed": ["foreign.so"]}]

    def links(binary, target, reader, *, allow_subset):
        assert binary and target and reader and allow_subset
        key = binary.decode()
        return assets[key]["native_links"]

    monkeypatch.setattr(verifier, "_links", links)
    with pytest.raises(ValueError, match="unreviewed maturin native link"):
        verifier.verify_assets(evidence, "/reader", lambda name: archives[name])


def test_maturin_archive_reader_rejects_members_and_oversized_binary(monkeypatch):
    bad_zip = io.BytesIO()
    with zipfile.ZipFile(bad_zip, "w") as archive:
        archive.writestr("foreign.exe", b"binary")
    with pytest.raises(ValueError, match="unexpected member"):
        verifier._binary(bad_zip.getvalue(), "maturin.zip")

    bad_tar = io.BytesIO()
    with tarfile.open(fileobj=bad_tar, mode="w:gz") as archive:
        archive.addfile(tarfile.TarInfo("foreign"))
    with pytest.raises(ValueError, match="unexpected member"):
        verifier._binary(bad_tar.getvalue(), "maturin.tar.gz")

    class Member:
        filename = "maturin.exe"
        file_size = 1

    class OversizedZip:
        def __init__(self, stream):
            assert stream.read() == b"archive"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def infolist(self):
            return [Member()]

        def read(self, member):
            assert member.filename == "maturin.exe"
            return b"four"

    monkeypatch.setattr(verifier, "MAX_BINARY_BYTES", 3)
    monkeypatch.setattr(verifier.zipfile, "ZipFile", OversizedZip)
    with pytest.raises(ValueError, match="executable exceeds"):
        verifier._binary(b"archive", "maturin.zip")


def test_maturin_download_is_bounded(monkeypatch):
    class Response:
        status = 200

        def read(self, limit):
            assert limit == 4
            return b"four"

        def close(self):
            pass

    class Opener:
        def open(self, request, timeout):
            assert request.method == "GET"
            assert request.full_url.endswith(
                "/maturin-x86_64-pc-windows-msvc.zip"
            )
            assert request.headers == {"User-agent": "cwl-release-gate"}
            assert timeout == 60
            return Response()

    monkeypatch.setattr(verifier, "MAX_ASSET_BYTES", 3)
    def build_opener(proxy_handler, redirect_handler):
        assert isinstance(proxy_handler, urllib.request.ProxyHandler)
        assert proxy_handler.proxies == {}
        assert isinstance(redirect_handler, verifier._ExactReleaseRedirect)
        return Opener()

    monkeypatch.setattr(verifier.urllib.request, "build_opener", build_opener)
    with pytest.raises(ValueError, match="asset exceeds"):
        verifier._download("maturin-x86_64-pc-windows-msvc.zip")


def test_maturin_download_closes_unsuccessful_responses_and_http_errors(monkeypatch):
    """Every rejected transport response releases its underlying connection."""
    closed = []

    class Response:
        status = 503

        def close(self):
            closed.append("response")

    class ResponseOpener:
        def open(self, _request, timeout):
            assert timeout == 60
            return Response()

    monkeypatch.setattr(
        verifier.urllib.request,
        "build_opener",
        lambda _proxy, _redirect: ResponseOpener(),
    )
    with pytest.raises(ValueError, match="HTTP 503"):
        verifier._download("maturin-x86_64-pc-windows-msvc.zip")
    assert closed == ["response"]

    transport_error = urllib.error.HTTPError(
        "https://github.com/asset", 502, "Bad Gateway", {}, io.BytesIO()
    )
    original_transport_close = transport_error.close

    def record_transport_close():
        """Record the close call without replacing the real resource cleanup."""
        closed.append("http-error")
        original_transport_close()

    monkeypatch.setattr(transport_error, "close", record_transport_close)

    class ErrorOpener:
        def open(self, _request, timeout):
            assert timeout == 60
            raise transport_error

    monkeypatch.setattr(
        verifier.urllib.request,
        "build_opener",
        lambda _proxy, _redirect: ErrorOpener(),
    )
    with pytest.raises(ValueError, match="HTTP 502"):
        verifier._download("maturin-x86_64-pc-windows-msvc.zip")
    assert closed == ["response", "http-error"]
    assert transport_error.closed


def test_maturin_download_rejects_unlisted_name_before_network(monkeypatch):
    """Caller-controlled paths and URLs never reach the network transport."""
    monkeypatch.setattr(
        verifier.urllib.request,
        "build_opener",
        lambda *_args, **_kwargs: pytest.fail("network opened for unlisted asset"),
    )
    for filename in ("foreign.zip", "../maturin.zip", "https://example.test/x", "x?y"):
        with pytest.raises(ValueError, match="asset name is unexpected"):
            verifier._download(filename)


@pytest.mark.parametrize(
    "location",
    [
        "http://release-assets.githubusercontent.com/asset",
        "https://example.test/asset",
        "https://127.0.0.1/asset",
        "https://release-assets.githubusercontent.com:invalid/asset",
        "https://[bad/asset",
        "file:///tmp/asset",
    ],
)
def test_maturin_download_rejects_unsafe_redirect(monkeypatch, location):
    """Only the credential-free GitHub release CDN redirect is admissible."""
    closed = []

    class Response:
        def close(self):
            closed.append("response")

    handler = verifier._ExactReleaseRedirect()
    handler.add_parent(
        type("Parent", (), {"open": lambda *_args, **_kwargs: pytest.fail("redirect opened")})()
    )
    request = urllib.request.Request(
        "https://github.com/PyO3/maturin/releases/download/v1.15.0/asset"
    )
    request.timeout = 60
    with pytest.raises(ValueError, match="redirect is not trusted"):
        handler.http_error_302(
            request, Response(), 302, "Found", {"Location": location}
        )
    assert closed == ["response"]


def test_maturin_download_follows_one_exact_release_cdn_redirect(monkeypatch):
    """The normal GitHub release redirect stays HTTPS and drops all authority."""
    closed = []
    sentinel = object()

    class Response:
        def close(self):
            closed.append("response")

    captured = {}

    class Parent:
        def open(self, request, timeout):
            captured.update(request=request, timeout=timeout)
            return sentinel

    handler = verifier._ExactReleaseRedirect()
    handler.add_parent(Parent())
    request = urllib.request.Request(
        "https://github.com/PyO3/maturin/releases/download/v1.15.0/asset"
    )
    request.timeout = 60
    location = (
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/123/asset?sig=abc"
    )
    assert (
        handler.http_error_302(
            request, Response(), 302, "Found", {"Location": location}
        )
        is sentinel
    )
    assert closed == ["response"]
    assert captured["timeout"] == 60
    assert captured["request"].full_url == location
    assert captured["request"].headers == {"User-agent": "cwl-release-gate"}
    assert captured["request"]._cwl_release_redirected is True


def test_maturin_downloader_has_no_scanner_suppressions():
    """The downloader must remove the general URL sink, not hide findings."""
    source = Path(verifier.__file__).read_text(encoding="utf-8")
    assert "nosemgrep" not in source
    assert "nosec" not in source
    assert "urlopen" not in source
    assert "HTTPSConnection" not in source


def test_maturin_main_reads_an_explicit_asset_root(tmp_path, monkeypatch):
    asset = tmp_path / "asset.zip"
    asset.write_bytes(b"asset")
    captured = {}

    def verify(evidence, reader, fetch):
        captured.update(evidence=evidence, reader=reader, raw=fetch(asset.name))

    monkeypatch.setattr(verifier, "verify_assets", verify)
    monkeypatch.setattr(verifier, "_reader", lambda: {"path": "/reader"})
    monkeypatch.setattr(sys, "argv", ["verify", "--asset-root", str(tmp_path)])
    verifier.main()
    assert captured["evidence"]["schema"] == "cwl.release-maturin-tool/1"
    assert captured["reader"] == "/reader"
    assert captured["raw"] == b"asset"


def test_maturin_verifier_has_complete_docstrings():
    """Every production entry point explains its trust-boundary responsibility."""
    assert verifier._binary.__doc__
    assert verifier.main.__doc__


def test_maturin_process_entrypoint_uses_the_bounded_downloader(monkeypatch):
    archives, assets, _, evidence = _asset_case()
    from scripts.ci import scan_release_native_links as scanner

    real_read_text = Path.read_text

    def read_text(path, *args, **kwargs):
        if path.name == "release_maturin_tool_evidence.json":
            return json.dumps(evidence)
        return real_read_text(path, *args, **kwargs)

    def links(binary, target, reader, *, allow_subset):
        assert target and reader and allow_subset
        return assets[binary.decode()]["native_links"]

    class Response:
        status = 200

        def __init__(self, raw):
            self.raw = raw

        def read(self, limit):
            assert limit == verifier.MAX_ASSET_BYTES + 1
            return self.raw

        def close(self):
            pass

    class Opener:
        def open(self, request, timeout):
            assert request.method == "GET"
            assert request.headers == {"User-agent": "cwl-release-gate"}
            assert timeout == 60
            return Response(archives[request.full_url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(scanner, "_reader", lambda: {"path": "/reader"})
    monkeypatch.setattr(scanner, "_links", links)
    monkeypatch.setattr(
        urllib.request, "build_opener", lambda _proxy, _redirect: Opener()
    )
    monkeypatch.setattr(sys, "argv", ["verify"])
    runpy.run_path(verifier.__file__, run_name="__main__")
