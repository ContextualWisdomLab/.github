"""Regression coverage for verified RIFF/WAVE assets in the Pingora edge gate."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

POLICY_MODULE_PATH = Path(__file__).parents[1] / "scripts" / "ci" / "pingora_edge_policy.py"
POLICY_MODULE_SPEC = importlib.util.spec_from_file_location(
    "pingora_edge_policy_wave_regression",
    POLICY_MODULE_PATH,
)
assert POLICY_MODULE_SPEC and POLICY_MODULE_SPEC.loader
policy_module = importlib.util.module_from_spec(POLICY_MODULE_SPEC)
sys.modules[POLICY_MODULE_SPEC.name] = policy_module
POLICY_MODULE_SPEC.loader.exec_module(policy_module)


def encoded_wave_response(wave_bytes: bytes) -> dict[str, object]:
    """Build one bounded GitHub Contents API response for RIFF/WAVE bytes."""

    return {
        "type": "file",
        "encoding": "base64",
        "size": len(wave_bytes),
        "content": base64.b64encode(wave_bytes).decode("ascii"),
    }


def pcm_wave_bytes() -> bytes:
    """Build a complete tiny PCM WAVE whose sample bytes are not valid UTF-8."""

    format_payload = (
        (1).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + (8_000).to_bytes(4, "little")
        + (16_000).to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
    )
    format_chunk = b"fmt " + len(format_payload).to_bytes(4, "little") + format_payload
    audio_payload = b"\xff\x00"
    audio_chunk = b"data" + len(audio_payload).to_bytes(4, "little") + audio_payload
    riff_payload = b"WAVE" + format_chunk + audio_chunk
    return b"RIFF" + len(riff_payload).to_bytes(4, "little") + riff_payload


def riff_wave_bytes(*wave_chunks: bytes) -> bytes:
    """Build one RIFF/WAVE envelope around caller-supplied chunks."""

    riff_payload = b"WAVE" + b"".join(wave_chunks)
    return b"RIFF" + len(riff_payload).to_bytes(4, "little") + riff_payload


def test_evaluate_pull_request_accepts_verified_wave_audio_asset() -> None:
    """A genuine patchless RIFF/WAVE resource is inert edge-policy evidence."""

    wave_bytes = pcm_wave_bytes()

    def policy_api_open(request_url: str, _auth_token: str) -> object:
        if "/pulls/1009/files" in request_url:
            return [
                {
                    "filename": "apps/desktop/src-tauri/resources/demo/late-night-set.wav",
                    "status": "added",
                }
            ]
        assert "/contents/apps/desktop/src-tauri/resources/demo/late-night-set.wav" in request_url
        return encoded_wave_response(wave_bytes)

    policy_violations = policy_module.evaluate_pull_request(
        api_url="https://api.github.test",
        repository="ContextualWisdomLab/bandscope",
        pull_request=1009,
        head_sha="a" * 40,
        event_action="synchronize",
        token="token",
        opener=policy_api_open,
    )

    assert policy_violations == ()


def test_wave_verifier_requires_complete_format_and_audio_chunks() -> None:
    """A RIFF/WAVE wrapper alone cannot bypass UTF-8 runtime inspection."""

    valid_wave = pcm_wave_bytes()
    header_only_wave = riff_wave_bytes()
    audio_only_chunk = b"data" + (2).to_bytes(4, "little") + b"\xff\x00"
    format_only_chunk = valid_wave[12:36]

    assert policy_module._is_complete_wave_audio(valid_wave)
    assert not policy_module._is_complete_wave_audio(header_only_wave)
    assert not policy_module._is_complete_wave_audio(riff_wave_bytes(audio_only_chunk))
    assert not policy_module._is_complete_wave_audio(riff_wave_bytes(format_only_chunk))


def test_wave_verifier_rejects_truncated_appended_and_misaligned_chunks() -> None:
    """Container-size and chunk-boundary drift fail closed before exemption."""

    valid_wave = pcm_wave_bytes()
    assert not policy_module._is_complete_wave_audio(valid_wave[:-1])
    assert not policy_module._is_complete_wave_audio(valid_wave + b"runtime")

    malformed_chunk = b"fmt " + (17).to_bytes(4, "little") + b"\x00" * 16
    assert not policy_module._is_complete_wave_audio(riff_wave_bytes(malformed_chunk))
