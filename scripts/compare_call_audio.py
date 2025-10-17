#!/usr/bin/env python3
"""
Compare inbound/outbound call recordings captured during RCA runs.

This utility complements `scripts/wav_quality_analyzer.py` by analysing
both sides of the call together.  It highlights DC offset, clipping,
spectral skew, silence ratios, and approximated pacing differences so we
can quickly spot "fast/garbled" regressions.

Usage:
    python scripts/compare_call_audio.py \
        --in logs/remote/.../recordings/in-*.wav \
        --out logs/remote/.../recordings/out-*.wav \
        [--json report.json]

Requires NumPy (already an optional project dependency).
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    np = None  # type: ignore

from wav_quality_analyzer import (  # type: ignore
    analyze_file,
    _read_wav_header,
    _to_pcm16,
)


def _ensure_numpy() -> None:
    if np is None:
        raise RuntimeError(
            "NumPy is required for spectral analysis. "
            "Install with `pip install numpy` inside your environment."
        )


def _load_pcm(path: str) -> Tuple[np.ndarray, int]:
    """Return PCM16 audio as a numpy array and the sample rate."""
    _ensure_numpy()
    header, raw = _read_wav_header(path)
    pcm_bytes, _mode = _to_pcm16(header, raw)
    if not pcm_bytes:
        return np.zeros(0, dtype=np.float32), header.rate
    pcm = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32)
    return pcm, header.rate


def _spectral_centroid(pcm: np.ndarray, rate: int) -> float:
    """Compute spectral centroid (Hz)."""
    if pcm.size == 0 or rate <= 0:
        return 0.0
    # Use a Hann window to reduce spectral leakage.
    window = np.hanning(pcm.size) if hasattr(np, "hanning") else np.ones_like(pcm, dtype=np.float64)
    windowed = pcm * window
    fft = np.fft.rfft(windowed)
    mag = np.abs(fft)
    if mag.sum() <= 0.0:
        return 0.0
    freqs = np.fft.rfftfreq(pcm.size, d=1.0 / rate)
    centroid = float((freqs * mag).sum() / mag.sum())
    return centroid


def _effective_duration_seconds(pcm: np.ndarray, rate: int, silence_threshold: float = 100.0) -> float:
    """Estimate effective voiced duration by summing non-silent 20 ms frames."""
    if pcm.size == 0 or rate <= 0:
        return 0.0
    frame_samples = int(rate * 0.02)
    if frame_samples <= 0:
        frame_samples = max(1, rate // 50)
    total = 0
    for start in range(0, pcm.size - frame_samples + 1, frame_samples):
        frame = pcm[start : start + frame_samples]
        rms = math.sqrt(float(np.mean(frame ** 2)))
        if rms >= silence_threshold:
            total += frame_samples
    return total / float(rate)


def _gather_stats(path: str) -> Dict[str, float]:
    """Collect extended stats for a single WAV."""
    _ensure_numpy()
    pcm, rate = _load_pcm(path)
    centroid = _spectral_centroid(pcm, rate)
    dc = float(pcm.mean()) if pcm.size else 0.0
    effective = _effective_duration_seconds(pcm, rate)
    return {
        "spectral_centroid_hz": centroid,
        "dc_offset": dc,
        "effective_duration_s": effective,
        "length_samples": int(pcm.size),
        "sample_rate": rate,
    }


def _observations(inbound: Dict[str, float], outbound: Dict[str, float], compare: Dict[str, float]) -> List[str]:
    """Generate human-readable observations."""
    notes: List[str] = []

    dc_in = inbound["base"]["mean"]
    dc_out = outbound["base"]["mean"]
    if abs(dc_in) > 600:
        notes.append(f"Inbound DC offset {dc_in} exceeds ±600 (possible upstream bias).")
    if abs(dc_out) > 600:
        notes.append(f"Outbound DC offset {dc_out} exceeds ±600 (likely audible hum / clipping).")

    if outbound["base"]["clip_ratio"] > 5e-4:
        notes.append(f"Outbound clipping ratio {outbound['base']['clip_ratio']:.5f} indicates repeated saturation.")

    centroid_ratio = compare["spectral_centroid_ratio"]
    if centroid_ratio > 1.3:
        notes.append(f"Outbound spectrum skewed high (centroid ratio {centroid_ratio:.2f}); playback likely fast/bright.")

    if compare["effective_duration_ratio"] < 0.9:
        notes.append(
            f"Outbound voiced duration is {compare['effective_duration_ratio']*100:.1f}% of inbound; "
            "frames are ending early (check pacer/drift)."
        )

    return notes


def compare_pair(inbound_path: str, outbound_path: str) -> Dict[str, object]:
    """Compare a single inbound/outbound WAV pair."""
    if np is None:
        _ensure_numpy()

    inbound_analysis = analyze_file(inbound_path)
    outbound_analysis = analyze_file(outbound_path)

    inbound_stats = _gather_stats(inbound_path)
    outbound_stats = _gather_stats(outbound_path)

    duration_ratio = (
        outbound_stats["effective_duration_s"] / inbound_stats["effective_duration_s"]
        if inbound_stats["effective_duration_s"] > 0
        else 0.0
    )
    centroid_ratio = (
        outbound_stats["spectral_centroid_hz"] / inbound_stats["spectral_centroid_hz"]
        if inbound_stats["spectral_centroid_hz"] > 0
        else 0.0
    )
    rms_ratio = (
        outbound_analysis.base.rms / max(1, inbound_analysis.base.rms)
        if inbound_analysis.base.rms
        else 0.0
    )

    comparison = {
        "duration_ratio": outbound_analysis.header.duration_s / max(1e-9, inbound_analysis.header.duration_s),
        "effective_duration_ratio": duration_ratio,
        "spectral_centroid_ratio": centroid_ratio,
        "rms_ratio": rms_ratio,
        "dc_offset_diff": outbound_analysis.base.mean - inbound_analysis.base.mean,
    }

    observations = _observations(
        {
            "base": asdict(inbound_analysis.base),
            "frames": asdict(inbound_analysis.frames),
            "extra": inbound_stats,
        },
        {
            "base": asdict(outbound_analysis.base),
            "frames": asdict(outbound_analysis.frames),
            "extra": outbound_stats,
        },
        comparison,
    )

    return {
        "inbound": {
            "path": inbound_path,
            "analysis": asdict(inbound_analysis),
            "extra": inbound_stats,
        },
        "outbound": {
            "path": outbound_path,
            "analysis": asdict(outbound_analysis),
            "extra": outbound_stats,
        },
        "comparison": comparison,
        "observations": observations,
    }


def _expand_one(pattern: str) -> List[str]:
    matches = glob.glob(pattern)
    if matches:
        return sorted(matches)
    if os.path.isfile(pattern):
        return [pattern]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare inbound/outbound call recordings.")
    parser.add_argument("--in", dest="inbound", required=True, help="Inbound WAV (or glob).")
    parser.add_argument("--out", dest="outbound", required=True, help="Outbound WAV (or glob).")
    parser.add_argument("--json", dest="json_out", help="Write JSON report to path.")
    args = parser.parse_args()

    inbound_files = _expand_one(args.inbound)
    outbound_files = _expand_one(args.outbound)
    if not inbound_files:
        print(f"No inbound files matched: {args.inbound}")
        return 1
    if not outbound_files:
        print(f"No outbound files matched: {args.outbound}")
        return 1

    if len(inbound_files) > 1 or len(outbound_files) > 1:
        print("Currently only a single inbound/outbound pair is supported. Pick the files explicitly.")
        return 1

    inbound_path = inbound_files[0]
    outbound_path = outbound_files[0]

    try:
        result = compare_pair(inbound_path, outbound_path)
    except Exception as exc:
        print(f"Failed to compare recordings: {exc}")
        return 1

    inbound = result["inbound"]
    outbound = result["outbound"]
    comp = result["comparison"]

    print(f"Inbound : {Path(inbound_path).name}")
    print(
        f"  RMS {inbound['analysis']['base']['rms']} | mean {inbound['analysis']['base']['mean']} "
        f"| clips {inbound['analysis']['base']['clip_count']} | "
        f"centroid {inbound['extra']['spectral_centroid_hz']:.1f} Hz | "
        f"voiced {inbound['extra']['effective_duration_s']:.2f}s"
    )
    print(f"Outbound: {Path(outbound_path).name}")
    print(
        f"  RMS {outbound['analysis']['base']['rms']} | mean {outbound['analysis']['base']['mean']} "
        f"| clips {outbound['analysis']['base']['clip_count']} | "
        f"centroid {outbound['extra']['spectral_centroid_hz']:.1f} Hz | "
        f"voiced {outbound['extra']['effective_duration_s']:.2f}s"
    )
    print(
        f"Derived : duration ratio {comp['duration_ratio']:.3f}, "
        f"effective voiced ratio {comp['effective_duration_ratio']:.3f}, "
        f"centroid ratio {comp['spectral_centroid_ratio']:.3f}, "
        f"RMS ratio {comp['rms_ratio']:.3f}, "
        f"DC diff {comp['dc_offset_diff']:.1f}"
    )
    observations: List[str] = result["observations"]
    if observations:
        print("\nObservations:")
        for note in observations:
            print(f"  - {note}")
    else:
        print("\nObservations: (none)")

    if args.json_out:
        try:
            with open(args.json_out, "w") as jf:
                json.dump(result, jf, indent=2)
            print(f"\nWrote JSON report to {args.json_out}")
        except Exception as exc:
            print(f"Failed to write JSON report: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
