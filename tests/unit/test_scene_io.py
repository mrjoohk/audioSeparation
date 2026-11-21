"""scene_io: float32 WAV encoding, staging commit (audit F-01, F-08)."""
import os
import wave

import numpy as np
import pytest
from scipy.io import wavfile

from simulator.scene_io import (
    SceneQCError,
    SceneStaging,
    canonical_json,
    read_wav,
    write_wav_float32,
)
from simulator.if_modules.orchestration import _write_wav


def test_wav_float32_roundtrip(tmp_path):
    x = np.array([-0.5, 0.0, 0.5, 1e-7, -1.0], dtype=np.float32)
    p = str(tmp_path / "a.wav")
    write_wav_float32(p, x, 16000)
    fs, y = wavfile.read(p)
    assert fs == 16000 and y.dtype == np.float32
    np.testing.assert_array_equal(x, y)


def test_legacy_writer_now_float32(tmp_path):
    """The audit reproduced [-0.5, 0, 0.5] being read back as int32."""
    p = str(tmp_path / "legacy.wav")
    _write_wav(np.array([-0.5, 0.0, 0.5], dtype=np.float32), p, 16000)
    _, y = wavfile.read(p)
    assert y.dtype == np.float32
    np.testing.assert_array_equal(y, [-0.5, 0.0, 0.5])
    with pytest.raises(wave.Error):  # IEEE float is not PCM; the stdlib reader refuses it
        wave.open(p).close()


def test_non_finite_audio_refused(tmp_path):
    with pytest.raises(SceneQCError):
        write_wav_float32(str(tmp_path / "bad.wav"), np.array([0.0, np.nan], np.float32), 16000)


def test_staging_commit_and_replace(tmp_path):
    st = SceneStaging(str(tmp_path), "sc")
    st.write_wav("x.wav", np.zeros(4, np.float32), 8000)
    final = st.commit()
    assert os.path.exists(os.path.join(final, "x.wav"))
    st2 = SceneStaging(str(tmp_path), "sc")
    st2.write_wav("y.wav", np.zeros(4, np.float32), 8000)
    st2.commit()
    assert sorted(os.listdir(final)) == ["y.wav"]
    assert sorted(os.listdir(tmp_path)) == ["sc"]  # staging root removed when empty


def test_staging_discard(tmp_path):
    st = SceneStaging(str(tmp_path), "sc")
    st.write_wav("x.wav", np.zeros(4, np.float32), 8000)
    st.discard()
    assert os.listdir(tmp_path) == []


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": [1, 2]}) == canonical_json({"a": [1, 2], "b": 1})
