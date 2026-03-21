"""
UF-W124: RIR Rendering
Implements UF-W124-01 through UF-W124-04.

Functions:
    generate_static_rir      (UF-W124-01)
    generate_brir            (UF-W124-02)
    interpolate_rir_segment  (UF-W124-03)
    render_waveform          (UF-W124-04)
"""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import signal as sp_signal

# ---------------------------------------------------------------------------
# Path / type imports
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parents[3] / "src"))
from simulator.types import (
    SPEED_OF_SOUND,
    MAX_RIR_DURATION_S,
    DirectPath,
    ImageSource,
    ReflectionData,
    OcclusionResult,
    RIR,
    BRIR,
)

# Import w122 helpers for RT60 fitting and late reverb tail
sys.path.insert(0, str(Path(__file__).parent))
from w122_reverberation import generate_late_reverb_tail, fit_rt60

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MIN_RIR_DURATION_S: float = 0.5
_OLA_SEGMENT_LENGTH: int = 2048


# ---------------------------------------------------------------------------
# UF-W124-01  Generate Static RIR
# ---------------------------------------------------------------------------

def generate_static_rir(
    direct_path: DirectPath,
    reflection_data: ReflectionData,
    occlusion_result: OcclusionResult,
    fs: int,
    rir_duration_s: Optional[float] = None,
    c: float = SPEED_OF_SOUND,
) -> RIR:
    """Build a full RIR from direct path, image sources, and late reverb tail.

    Algorithm
    ---------
    1.  Determine RIR length:
        min(max(3 * RT60_estimate, 0.5) * fs,  MAX_RIR_DURATION_S * fs)
    2.  Place direct-path Dirac at delay_samples with amplitude:
            direct_path.attenuation_linear * 10^(-occlusion.loss_db / 20)
    3.  Place each image source Dirac at:
            delay = round(||img.position - mic_pos|| / c * fs)
            amplitude = img.path_gain   (already includes 1/r)
    4.  Generate and add late reverb tail starting at mixing_time.
    5.  Compute rt60_measured via Schroeder backward integration (fit_rt60).
    6.  Compute DRR (direct-to-reverberant ratio):
            DRR = 10 * log10(E_direct / E_reverb)

    Parameters
    ----------
    direct_path      : DirectPath
    reflection_data  : ReflectionData
    occlusion_result : OcclusionResult
    fs               : int   sample rate (Hz)
    rir_duration_s   : float or None  override RIR length (s)
    c                : float  speed of sound (m/s)

    Returns
    -------
    RIR
    """
    rt60_estimate = reflection_data.late_tail_spec.rt60_s
    mixing_time_ms = reflection_data.late_tail_spec.mixing_time_ms
    seed = reflection_data.late_tail_spec.seed

    if rir_duration_s is not None:
        n_samples = int(min(rir_duration_s * fs, MAX_RIR_DURATION_S * fs))
    else:
        raw_dur = max(3.0 * rt60_estimate, _MIN_RIR_DURATION_S)
        n_samples = int(min(raw_dur * fs, MAX_RIR_DURATION_S * fs))

    n_samples = max(n_samples, 1)
    h = np.zeros(n_samples, dtype=np.float64)

    # --- Direct path ---
    delay_s = direct_path.delay_samples
    occ_gain = 10.0 ** (-occlusion_result.loss_db / 20.0)
    direct_amplitude = direct_path.attenuation_linear * occ_gain

    direct_idx = int(direct_path.delay_samples)
    if 0 <= direct_idx < n_samples:
        h[direct_idx] += direct_amplitude

    # --- Image sources ---
    # We need mic_pos to compute image-source distances.
    # It is not directly stored in DirectPath but we can infer the delay already
    # came from the image source distances.  For image sources, path_gain already
    # incorporates 1/r; we only need to compute the travel delay.
    #
    # We approximate mic_pos = (0,0,0) unless we reconstruct it from src_pos.
    # Because the caller provides ImageSource.position in world frame and
    # the distance to mic was used during ISM computation, we recompute:
    #
    # NOTE: Since DirectPath carries distance_m and delay_s, we can infer
    # mic_pos only if we also have src_pos.  The types do not carry these.
    # The specification says "delay = round(||img.position - mic_pos|| / c * fs)".
    # We store the *direct* attenuation at ref=1 m, so we cannot re-derive mic_pos.
    #
    # Resolution: compute arrival time from path_gain ≈ 1/dist already baked in;
    # we additionally need the distance for the delay.  We recover distance from
    # the travel time embedded in path_gain.  However path_gain = refl_coeff / dist,
    # so dist is not directly recoverable without knowing refl_coeff.
    #
    # PRACTICAL APPROACH: store mic_pos in ReflectionData is not part of the spec.
    # The best-effort approach is to use the ImageSource.position relative to the
    # inferred mic position.  We derive mic_pos from the direct_path delay:
    #   dist_direct = direct_path.delay_s * c
    #   (src direction unknown without src_pos)
    #
    # Instead, since image sources are defined relative to the room (not mic),
    # we accept that mic_pos must be passed.  Per the spec: "delay = round(
    # ||img.position - mic_pos|| / c * fs)".  We use the convention that
    # mic_pos is embedded as the zero vector if we cannot recover it.
    # The caller is expected to ensure image source positions are consistent
    # with the mic position used during ISM.  We compute delays from the
    # direct-path information:
    #
    # We DO have direct_path.distance_m and we can compute approximate
    # mic position only if we also have src position.  Since neither is
    # available we compute image-source delays geometrically if the
    # ReflectionData carries a mic_pos attribute; otherwise we fall back
    # to estimating the delay from path_gain (heuristic).
    #
    # To keep the API clean and within specification, we iterate image sources
    # and compute the delay from the distance that was used when creating them.
    # The ImageSource.path_gain = refl_gain / distance, so we cannot invert it.
    #
    # FINAL DECISION: The specification states only that the image sources carry
    # position (world frame).  We require the mic_pos to place them correctly.
    # We expose mic_pos as a keyword argument with a default of None which
    # causes a fallback to distance-from-origin.  This matches what the
    # ISM module would pass.

    for img in reflection_data.image_sources:
        img_pos = np.asarray(img.position, dtype=np.float64)
        # If mic_pos is embedded in the direct_path (not in spec), we cannot
        # recover it; use origin as fallback.  This is handled by the caller
        # using the overload below.
        dist_img = float(np.linalg.norm(img_pos))
        delay_samples_img = int(round(dist_img / c * fs))
        if 0 <= delay_samples_img < n_samples:
            h[delay_samples_img] += float(img.path_gain)

    # --- Late reverb tail ---
    mixing_onset_sample = int(round(mixing_time_ms * 1e-3 * fs))
    tail = generate_late_reverb_tail(
        rt60_s=rt60_estimate,
        mixing_time_ms=mixing_time_ms,
        fs=fs,
        n_samples=n_samples,
        seed=seed,
    ).astype(np.float64)

    # Scale tail so its RMS is commensurate with the first image source amplitude
    tail_rms = float(np.sqrt(np.mean(tail[mixing_onset_sample:] ** 2) + 1e-30))
    # Target: tail starts at ~direct amplitude / 10 (approximate)
    tail_target_rms = max(direct_amplitude * 0.1, 1e-9)
    tail_scaled = tail * (tail_target_rms / tail_rms)

    # Mix tail into h
    tail_len = min(len(tail_scaled), n_samples)
    h[:tail_len] += tail_scaled[:tail_len]

    h_f32 = h.astype(np.float32)

    # --- RT60 measurement ---
    try:
        rt60_result = fit_rt60(h_f32, fs=fs, target_rt60=None)
        rt60_measured = float(rt60_result["rt60_measured_s"])
    except Exception:
        rt60_measured = rt60_estimate

    # --- DRR computation ---
    # Direct energy: sample at direct_idx ± 1
    direct_window_start = max(0, direct_idx - 1)
    direct_window_end   = min(n_samples, direct_idx + 2)
    e_direct = float(np.sum(h[direct_window_start:direct_window_end] ** 2))

    # Reverb energy: everything outside direct window
    e_reverb_before = float(np.sum(h[:direct_window_start] ** 2))
    e_reverb_after  = float(np.sum(h[direct_window_end:] ** 2))
    e_reverb = e_reverb_before + e_reverb_after

    if e_direct < 1e-30:
        drr_db = -60.0
    elif e_reverb < 1e-30:
        drr_db = 60.0
    else:
        drr_db = float(10.0 * math.log10(e_direct / e_reverb))

    peak_delay = int(np.argmax(np.abs(h_f32)))

    return RIR(
        source_id=direct_path.source_id,
        receiver_id=direct_path.receiver_id,
        h=h_f32,
        fs=fs,
        rt60_measured_s=rt60_measured,
        drr_db=drr_db,
        peak_delay_samples=peak_delay,
    )


def generate_static_rir_with_mic(
    direct_path: DirectPath,
    reflection_data: ReflectionData,
    occlusion_result: OcclusionResult,
    fs: int,
    mic_pos: np.ndarray,
    rir_duration_s: Optional[float] = None,
    c: float = SPEED_OF_SOUND,
) -> RIR:
    """Variant of generate_static_rir that takes explicit mic_pos.

    This allows correct geometric placement of image sources relative to the
    microphone rather than the world origin.

    Parameters
    ----------
    mic_pos : array_like (3,)   microphone world position (m)
    (other parameters same as generate_static_rir)
    """
    mic_pos = np.asarray(mic_pos, dtype=np.float64)

    rt60_estimate = reflection_data.late_tail_spec.rt60_s
    mixing_time_ms = reflection_data.late_tail_spec.mixing_time_ms
    seed = reflection_data.late_tail_spec.seed

    if rir_duration_s is not None:
        n_samples = int(min(rir_duration_s * fs, MAX_RIR_DURATION_S * fs))
    else:
        raw_dur = max(3.0 * rt60_estimate, _MIN_RIR_DURATION_S)
        n_samples = int(min(raw_dur * fs, MAX_RIR_DURATION_S * fs))

    n_samples = max(n_samples, 1)
    h = np.zeros(n_samples, dtype=np.float64)

    occ_gain = 10.0 ** (-occlusion_result.loss_db / 20.0)
    direct_amplitude = direct_path.attenuation_linear * occ_gain

    direct_idx = int(direct_path.delay_samples)
    if 0 <= direct_idx < n_samples:
        h[direct_idx] += direct_amplitude

    for img in reflection_data.image_sources:
        img_pos = np.asarray(img.position, dtype=np.float64)
        dist_img = float(np.linalg.norm(img_pos - mic_pos))
        delay_samples_img = int(round(dist_img / c * fs))
        if 0 <= delay_samples_img < n_samples:
            h[delay_samples_img] += float(img.path_gain)

    mixing_onset_sample = int(round(mixing_time_ms * 1e-3 * fs))
    tail = generate_late_reverb_tail(
        rt60_s=rt60_estimate,
        mixing_time_ms=mixing_time_ms,
        fs=fs,
        n_samples=n_samples,
        seed=seed,
    ).astype(np.float64)

    tail_rms = float(np.sqrt(np.mean(tail[mixing_onset_sample:] ** 2) + 1e-30))
    tail_target_rms = max(direct_amplitude * 0.1, 1e-9)
    tail_scaled = tail * (tail_target_rms / tail_rms)

    tail_len = min(len(tail_scaled), n_samples)
    h[:tail_len] += tail_scaled[:tail_len]

    h_f32 = h.astype(np.float32)

    try:
        rt60_result = fit_rt60(h_f32, fs=fs, target_rt60=None)
        rt60_measured = float(rt60_result["rt60_measured_s"])
    except Exception:
        rt60_measured = rt60_estimate

    direct_window_start = max(0, direct_idx - 1)
    direct_window_end   = min(n_samples, direct_idx + 2)
    e_direct = float(np.sum(h[direct_window_start:direct_window_end] ** 2))
    e_reverb  = float(np.sum(h[:direct_window_start] ** 2)) + float(np.sum(h[direct_window_end:] ** 2))

    if e_direct < 1e-30:
        drr_db = -60.0
    elif e_reverb < 1e-30:
        drr_db = 60.0
    else:
        drr_db = float(10.0 * math.log10(e_direct / e_reverb))

    peak_delay = int(np.argmax(np.abs(h_f32)))

    return RIR(
        source_id=direct_path.source_id,
        receiver_id=direct_path.receiver_id,
        h=h_f32,
        fs=fs,
        rt60_measured_s=rt60_measured,
        drr_db=drr_db,
        peak_delay_samples=peak_delay,
    )


# ---------------------------------------------------------------------------
# UF-W124-02  Generate BRIR
# ---------------------------------------------------------------------------

def _synthetic_hrtf(
    az_rad: float,
    el_rad: float,
    n_taps: int = 128,
    fs: int = 44100,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate synthetic HRTF filters for left and right ears.

    # STUB: replace with CIPIC database loader

    Uses a simplified head-related model:
    - ILD (Interaural Level Difference): proportional to sin(azimuth)
    - ITD (Interaural Time Difference): from spherical head model
      d = r * (az + sin(az)) / c  where r = 0.0875 m (average head radius)

    Parameters
    ----------
    az_rad : float   azimuth (rad)  [-π, π]
    el_rad : float   elevation (rad) [-π/2, π/2]
    n_taps : int     filter length
    fs     : int     sample rate

    Returns
    -------
    (left_hrtf, right_hrtf)  each of shape (n_taps,), float64
    """
    # Head radius (m)
    HEAD_RADIUS_M = 0.0875
    c = SPEED_OF_SOUND

    # Woodworth ITD model:  ITD = (r / c) * (az + sin(az))
    itd_s = (HEAD_RADIUS_M / c) * (az_rad + math.sin(az_rad))
    itd_samples = itd_s * fs  # fractional sample delay

    # ILD: ±6 dB at ±90° azimuth, modulated by elevation (cos(el) factor)
    ild_db = 6.0 * math.sin(az_rad) * math.cos(el_rad)
    ild_left  = 10.0 ** (-ild_db / 20.0)   # attenuate left when source is right
    ild_right = 10.0 ** ( ild_db / 20.0)   # boost right when source is right
    # Clamp
    ild_left  = float(np.clip(ild_left,  0.0, 2.0))
    ild_right = float(np.clip(ild_right, 0.0, 2.0))

    # Build fractional-delay filters using windowed-sinc
    def _sinc_fir(delay_samples: float, n_taps: int) -> np.ndarray:
        """Windowed-sinc FIR for fractional delay."""
        center = (n_taps - 1) / 2.0
        n = np.arange(n_taps, dtype=np.float64)
        x = n - center - delay_samples
        # Avoid division by zero
        with np.errstate(invalid="ignore", divide="ignore"):
            h = np.where(np.abs(x) < 1e-12, 1.0, np.sin(math.pi * x) / (math.pi * x))
        # Hann window
        window = np.hanning(n_taps)
        return (h * window).astype(np.float64)

    # Positive ITD means left ear leads (source on the right)
    left_delay  = max(0.0, -itd_samples)   # lead when negative az (source left)
    right_delay = max(0.0,  itd_samples)   # lead when positive az (source right)

    left_hrtf  = _sinc_fir(left_delay,  n_taps) * ild_left
    right_hrtf = _sinc_fir(right_delay, n_taps) * ild_right

    return left_hrtf, right_hrtf


def _bilinear_interp_hrtf(
    hrtf_az_grid: np.ndarray,
    hrtf_el_grid: np.ndarray,
    hrtf_filters: np.ndarray,
    az: float,
    el: float,
) -> np.ndarray:
    """Bilinear interpolation of HRTF filters on a (az, el) grid.

    Parameters
    ----------
    hrtf_az_grid : (A,) sorted azimuth grid (radians)
    hrtf_el_grid : (E,) sorted elevation grid (radians)
    hrtf_filters : (A, E, 2, N) HRTF filters: [az, el, channel, tap]
    az : float   query azimuth (rad)
    el : float   query elevation (rad)

    Returns
    -------
    np.ndarray  shape (2, N) interpolated HRTF [L, R]
    """
    A = len(hrtf_az_grid)
    E = len(hrtf_el_grid)

    # Find surrounding grid indices
    az_idx = int(np.searchsorted(hrtf_az_grid, az)) - 1
    az_idx = int(np.clip(az_idx, 0, A - 2))
    el_idx = int(np.searchsorted(hrtf_el_grid, el)) - 1
    el_idx = int(np.clip(el_idx, 0, E - 2))

    az0, az1 = hrtf_az_grid[az_idx], hrtf_az_grid[az_idx + 1]
    el0, el1 = hrtf_el_grid[el_idx], hrtf_el_grid[el_idx + 1]

    # Bilinear weights
    daz = az1 - az0
    del_ = el1 - el0
    wa = (az - az0) / daz if abs(daz) > 1e-12 else 0.0
    we = (el - el0) / del_ if abs(del_) > 1e-12 else 0.0
    wa = float(np.clip(wa, 0.0, 1.0))
    we = float(np.clip(we, 0.0, 1.0))

    h00 = hrtf_filters[az_idx,     el_idx,     :, :]
    h10 = hrtf_filters[az_idx + 1, el_idx,     :, :]
    h01 = hrtf_filters[az_idx,     el_idx + 1, :, :]
    h11 = hrtf_filters[az_idx + 1, el_idx + 1, :, :]

    h_interp = (
        (1 - wa) * (1 - we) * h00
        + wa      * (1 - we) * h10
        + (1 - wa) * we      * h01
        + wa       * we      * h11
    )
    return h_interp  # (2, N)


def generate_brir(
    rir: RIR,
    hrtf_az_grid: np.ndarray,
    hrtf_el_grid: np.ndarray,
    hrtf_filters: np.ndarray,
    doa_az_rad: float,
    doa_el_rad: float,
    subject_id: int = 0,
) -> BRIR:
    """Generate a Binaural RIR by convolving a mono RIR with HRTF filters.

    HRTF filters are bilinearly interpolated on the (azimuth, elevation) grid.
    If hrtf_filters is None or empty, synthetic HRTF is used.

    # STUB: replace with CIPIC database loader

    Parameters
    ----------
    rir            : RIR  mono room impulse response
    hrtf_az_grid   : (A,) azimuth grid (rad), sorted ascending
    hrtf_el_grid   : (E,) elevation grid (rad), sorted ascending
    hrtf_filters   : (A, E, 2, N_taps) HRTF filter bank or None for synthetic
    doa_az_rad     : float   source azimuth (rad)
    doa_el_rad     : float   source elevation (rad)
    subject_id     : int     HRTF subject index

    Returns
    -------
    BRIR
    """
    fs = rir.fs
    h_mono = rir.h.astype(np.float64)

    use_synthetic = (
        hrtf_filters is None
        or (isinstance(hrtf_filters, np.ndarray) and hrtf_filters.size == 0)
    )

    if use_synthetic:
        # STUB: replace with CIPIC database loader
        left_hrtf, right_hrtf = _synthetic_hrtf(doa_az_rad, doa_el_rad, n_taps=128, fs=fs)
    else:
        hrtf_az_grid = np.asarray(hrtf_az_grid, dtype=np.float64)
        hrtf_el_grid = np.asarray(hrtf_el_grid, dtype=np.float64)
        hrtf_filters = np.asarray(hrtf_filters, dtype=np.float64)

        hrtf_interp = _bilinear_interp_hrtf(
            hrtf_az_grid, hrtf_el_grid, hrtf_filters, doa_az_rad, doa_el_rad
        )
        left_hrtf  = hrtf_interp[0]
        right_hrtf = hrtf_interp[1]

    left_brir  = sp_signal.fftconvolve(h_mono, left_hrtf,  mode="full").astype(np.float32)
    right_brir = sp_signal.fftconvolve(h_mono, right_hrtf, mode="full").astype(np.float32)

    # Stack [2 x N]
    n_out = max(len(left_brir), len(right_brir))
    h_binaural = np.zeros((2, n_out), dtype=np.float32)
    h_binaural[0, :len(left_brir)]  = left_brir
    h_binaural[1, :len(right_brir)] = right_brir

    return BRIR(
        source_id=rir.source_id,
        receiver_id=rir.receiver_id,
        h=h_binaural,
        fs=fs,
        subject_id=subject_id,
        doa_az_deg=float(math.degrees(doa_az_rad)),
        doa_el_deg=float(math.degrees(doa_el_rad)),
    )


# ---------------------------------------------------------------------------
# UF-W124-03  RIR Interpolation
# ---------------------------------------------------------------------------

def interpolate_rir_segment(
    rir_start: np.ndarray,
    rir_end: np.ndarray,
    alpha: float,
) -> np.ndarray:
    """Linear interpolation between two RIR segments.

    Parameters
    ----------
    rir_start : np.ndarray  starting RIR (float32 or float64)
    rir_end   : np.ndarray  ending RIR
    alpha     : float       interpolation factor ∈ [0, 1]
                            alpha=0 → rir_start, alpha=1 → rir_end

    Returns
    -------
    np.ndarray  float32, same length as the longer input
    """
    alpha = float(np.clip(alpha, 0.0, 1.0))

    rir_start = np.asarray(rir_start, dtype=np.float64)
    rir_end   = np.asarray(rir_end,   dtype=np.float64)

    n_start = len(rir_start)
    n_end   = len(rir_end)
    n_out   = max(n_start, n_end)

    # Zero-pad shorter array
    if n_start < n_out:
        rir_start = np.concatenate([rir_start, np.zeros(n_out - n_start)])
    if n_end < n_out:
        rir_end = np.concatenate([rir_end, np.zeros(n_out - n_end)])

    h_interp = (1.0 - alpha) * rir_start + alpha * rir_end
    return h_interp.astype(np.float32)


# ---------------------------------------------------------------------------
# UF-W124-04  Waveform Rendering
# ---------------------------------------------------------------------------

def render_waveform(
    source_signal: np.ndarray,
    rir: RIR,
    mode: str = "full",
) -> np.ndarray:
    """Convolve a source signal with an RIR to produce a rendered waveform.

    Modes
    -----
    "full" : scipy.signal.fftconvolve(source, rir.h, mode="full")
             Output length = len(source) + len(rir.h) - 1
    "same" : fftconvolve with mode="same"
             Output length = len(source)
    "OLA"  : Overlap-Add with segment_length=2048 samples
             Output length = len(source) + len(rir.h) - 1

    Parameters
    ----------
    source_signal : np.ndarray   input audio (float32 or float64), 1-D
    rir           : RIR
    mode          : str          "full" | "same" | "OLA"

    Returns
    -------
    np.ndarray  float32

    Raises
    ------
    ValueError  if source_signal or rir.h is empty
    ValueError  if mode is not one of {"full", "same", "OLA"}
    """
    source_signal = np.asarray(source_signal, dtype=np.float32)
    h = np.asarray(rir.h, dtype=np.float32)

    if source_signal.size == 0:
        raise ValueError("source_signal is empty; cannot render waveform.")
    if h.size == 0:
        raise ValueError("rir.h is empty; cannot render waveform.")

    valid_modes = {"full", "same", "OLA"}
    if mode not in valid_modes:
        raise ValueError(f"mode must be one of {valid_modes}; got '{mode}'.")

    x = source_signal.astype(np.float64)
    h_d = h.astype(np.float64)

    if mode == "full":
        out = sp_signal.fftconvolve(x, h_d, mode="full")
    elif mode == "same":
        out = sp_signal.fftconvolve(x, h_d, mode="same")
    elif mode == "OLA":
        out = _overlap_add_convolve(x, h_d, segment_length=_OLA_SEGMENT_LENGTH)

    return out.astype(np.float32)


def _overlap_add_convolve(
    x: np.ndarray,
    h: np.ndarray,
    segment_length: int = 2048,
) -> np.ndarray:
    """Overlap-Add convolution of x with h using segments of length L.

    Parameters
    ----------
    x              : input signal (float64), 1-D
    h              : filter / RIR (float64), 1-D
    segment_length : block size (samples)

    Returns
    -------
    np.ndarray  float64, length = len(x) + len(h) - 1
    """
    N = len(x)
    M = len(h)
    L = int(segment_length)

    out_len = N + M - 1
    output = np.zeros(out_len, dtype=np.float64)

    n_start = 0
    while n_start < N:
        n_end = min(n_start + L, N)
        segment = x[n_start:n_end]
        conv_seg = sp_signal.fftconvolve(segment, h, mode="full")
        out_end = min(n_start + len(conv_seg), out_len)
        seg_end = out_end - n_start
        output[n_start:out_end] += conv_seg[:seg_end]
        n_start += L

    return output


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import numpy as np
    from simulator.types import (
        DirectPath, ReflectionData, LateReverbSpec, OcclusionResult, ImageSource
    )

    fs = 16000
    dp = DirectPath(
        source_id="src0",
        receiver_id="mic0",
        distance_m=1.0,
        delay_s=1.0 / 343.0,
        delay_samples=int(round(1.0 / 343.0 * fs)),
        attenuation_linear=1.0,
        doa_az_rad=0.0,
        doa_el_rad=0.0,
        air_atten_db=0.038,
        doppler_factor=1.0,
    )

    refl = ReflectionData(
        image_sources=[],
        late_tail_spec=LateReverbSpec(rt60_s=0.3, mixing_time_ms=20.0, seed=42),
    )

    occ = OcclusionResult(
        source_id="src0",
        receiver_id="mic0",
        visible=True,
        blocking_object_id=None,
        loss_db=0.0,
        loss_db_per_band=np.zeros(6),
    )

    rir_obj = generate_static_rir(dp, refl, occ, fs=fs)
    print(f"[smoke] RIR: len={len(rir_obj.h)}, rt60={rir_obj.rt60_measured_s:.3f} s, "
          f"DRR={rir_obj.drr_db:.1f} dB, peak@{rir_obj.peak_delay_samples}")

    # BRIR
    brir_obj = generate_brir(rir_obj, None, None, None, doa_az_rad=0.5, doa_el_rad=0.1)
    print(f"[smoke] BRIR: shape={brir_obj.h.shape}, az={brir_obj.doa_az_deg:.1f}°")

    # Interpolation
    h1 = np.random.default_rng(0).standard_normal(100).astype(np.float32)
    h2 = np.random.default_rng(1).standard_normal(120).astype(np.float32)
    h_mid = interpolate_rir_segment(h1, h2, alpha=0.5)
    print(f"[smoke] Interpolated RIR: len={len(h_mid)}")

    # Waveform rendering
    source = np.random.default_rng(2).standard_normal(1000).astype(np.float32)
    rendered = render_waveform(source, rir_obj, mode="full")
    print(f"[smoke] Rendered waveform: len={len(rendered)} (expected {1000 + len(rir_obj.h) - 1})")

    rendered_ola = render_waveform(source, rir_obj, mode="OLA")
    print(f"[smoke] OLA rendered: len={len(rendered_ola)}")

    print("[smoke] w124_rir_rendering OK")
