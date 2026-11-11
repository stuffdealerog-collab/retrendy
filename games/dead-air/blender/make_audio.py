"""STRELKA — trailer track, synthesised from scratch (numpy/scipy). 160 BPM.

Structure follows the match structure of the game:
  0-16   the speaker hums on the ground (muffled, diegetic)
  16-32  the drop: every hit in the picture sits on this grid
  32-40  ШУХЕР — the music is cut, only a far siren and a heartbeat
  40-48  the drop again, 48 = last hit, tail to 56
"""
import os
import sys
import wave

import numpy as np
from scipy.signal import butter, lfilter

SR, BPM = 44100, 160.0
BEAT = 60.0 / BPM
BEATS = 56
N = int(SR * BEAT * BEATS) + SR // 2
rng = np.random.default_rng(404)


def filt(x, f, kind="low", order=2):
    b, a = butter(order, np.array(f) / (SR / 2), kind)
    return lfilter(b, a, x)


def env(n, a=0.002, d=0.2):
    t = np.arange(n) / SR
    return np.minimum(1, t / a) * np.exp(-t / d)


def add(buf, sig, beat, gain=1.0):
    i = int(beat * BEAT * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[:j - i] * gain


def note(semi_from_a4):
    return 440.0 * 2 ** (semi_from_a4 / 12)


def kick():
    n = int(0.32 * SR); t = np.arange(n) / SR
    f = 46 + 110 * np.exp(-t / 0.035)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.13)
    s += filt(rng.normal(0, 1, n), 3000, "high") * np.exp(-t / 0.004) * 0.25
    return np.tanh(s * 2.4)


def bass808(f0, beats, slide=0.0):
    n = int(beats * BEAT * SR); t = np.arange(n) / SR
    f = f0 * 2 ** (slide * np.clip(t / (beats * BEAT), 0, 1) / 12) + 30 * np.exp(-t / 0.02)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR)
    e = np.minimum(1, t / 0.004) * np.exp(-t / (beats * BEAT * 0.9))
    return np.tanh(s * e * 3.0) * 0.9


def clap():
    n = int(0.22 * SR); t = np.arange(n) / SR
    x = filt(rng.normal(0, 1, n), [900, 3800], "band")
    e = sum(np.exp(-np.maximum(0, t - d) / 0.012) * (t >= d) for d in (0.0, 0.011, 0.023)) + 0.7 * np.exp(-t / 0.07)
    return x * e * 0.7


def hat(d=0.022):
    n = int(0.09 * SR); t = np.arange(n) / SR
    return filt(rng.normal(0, 1, n), 7500, "high") * np.exp(-t / d) * 0.32


def cowbell(f, dur=0.34):
    n = int(dur * SR); t = np.arange(n) / SR
    s = np.sign(np.sin(2 * np.pi * f * t)) + 0.8 * np.sign(np.sin(2 * np.pi * f * 1.504 * t))
    s = filt(s, [f * 0.7, min(9000, f * 6)], "band")
    return np.tanh(s * env(n, 0.001, 0.11) * 2.2) * 0.5


def pad(freqs, beats):
    n = int(beats * BEAT * SR); t = np.arange(n) / SR
    s = np.zeros(n)
    for f in freqs:
        for det in (-0.006, 0.0, 0.007):
            ph = rng.uniform(0, 1)
            s += 2 * (((f * (1 + det)) * t + ph) % 1.0) - 1
    s = filt(s, 700, "low", 2)
    e = np.minimum(1, t / 0.6) * np.minimum(1, (t[-1] - t) / 0.5)
    return s * e * 0.05


def punch(big=1.0):
    n = int(0.25 * SR); t = np.arange(n) / SR
    body = np.sin(2 * np.pi * np.cumsum(70 + 160 * np.exp(-t / 0.02)) / SR) * np.exp(-t / 0.07)
    crack = filt(rng.normal(0, 1, n), [500, 5000], "band") * np.exp(-t / 0.02)
    return np.tanh((body * 1.4 + crack * 1.1) * (1.2 + big)) * 0.8


def reverb(x, length=1.4, wet=0.22):
    n = int(length * SR)
    ir = rng.normal(0, 1, n) * np.exp(-np.arange(n) / (SR * length / 5))
    ir = filt(ir, 3500, "low")
    ir /= np.sqrt((ir ** 2).sum())
    y = np.fft.irfft(np.fft.rfft(x, len(x) + n) * np.fft.rfft(ir, len(x) + n))[:len(x)]
    return x + wet * y


# E minor. Semitones from A4.
E, Fs, G, A, B, C_, D = -5, -3, -2, 0, 2, 3, 5
MEL = [(0, E + 12), (1, None), (1.5, G + 12), (2, E + 12), (3, B), (3.5, D + 12),
       (4, E + 12), (5, None), (5.5, G + 12), (6, A + 12), (6.5, G + 12), (7, E + 12), (7.5, D + 12)]
BASS = [(0, E, 1.5, 0), (1.5, E, 1.0, 0), (3, G, 1.0, -3), (4, E, 1.5, 0), (5.5, C_ - 12, 1.0, 0), (7, D - 12, 1.0, 2)]


def build():
    drums, mus, lead, sfx = np.zeros(N), np.zeros(N), np.zeros(N), np.zeros(N)
    K_, C2, H_ = kick(), clap(), hat()
    # ---- intro: the track leaks out of the speaker on the ground
    intro = np.zeros(N)
    for bar2 in range(0, 16, 8):
        for (b, s) in MEL:
            if s is not None:
                add(intro, cowbell(note(s)), bar2 + b, 0.9)
        for b in range(0, 8, 2):
            add(intro, K_, bar2 + b, 0.7)
    intro = filt(intro, [350, 2200], "band", 2) * 0.55
    mus += intro
    mus += np.pad(pad([note(E - 24), note(B - 24), note(G - 12)], 16), (0, N - int(16 * BEAT * SR)))[:N]
    crackle = (rng.random(N) > 0.9993) * rng.normal(0, 0.5, N)
    mus[:int(16 * BEAT * SR)] += filt(crackle, 2500, "high")[:int(16 * BEAT * SR)] * 0.6
    n_r = int(2 * BEAT * SR); t = np.arange(n_r) / n_r                       # riser 14-16
    add(sfx, filt(rng.normal(0, 1, n_r), 2500, "high") * t ** 2.5 * 0.35, 14)
    # ---- drops
    for start, bars in ((16, 4), (40, 2)):
        for bar in range(bars):
            b0 = start + bar * 4
            for b in (0, 1.5, 2.5):
                add(drums, K_, b0 + b, 1.0)
            for b in (1, 3):
                add(drums, C2, b0 + b, 1.0)
            for i in range(8):
                add(drums, H_, b0 + i * 0.5, 0.9 if i % 2 == 0 else 0.6)
            if bar % 2 == 1:
                for i in range(4):
                    add(drums, hat(0.012), b0 + 3 + i * 0.125 + 0.5, 0.5 + 0.1 * i)
        for b2 in range(0, bars * 4, 8):
            for (b, s) in MEL:
                if s is not None:
                    add(lead, cowbell(note(s + (12 if start == 40 else 0))), start + b2 + b, 1.0)
            for (b, s, ln, sl) in BASS:
                add(mus, bass808(note(s - 36), ln, sl), start + b2 + b, 1.0)
    # last hit
    add(drums, K_, 48, 1.2); add(mus, bass808(note(E - 36), 5, -12), 48, 1.1)
    add(lead, cowbell(note(E + 12), 0.9), 48, 1.2)
    # ---- shukher: silence, a far siren, a heartbeat
    n_s = int(7.4 * BEAT * SR); t = np.arange(n_s) / SR
    f = 620 + 240 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.62 * t))
    siren = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(1, t / 0.8) * np.minimum(1, (t[-1] - t) / 0.3)
    add(sfx, filt(siren, 1100, "low") * 0.07, 32.5)
    drone = np.sin(2 * np.pi * 41 * t) * 0.12 * np.minimum(1, t / 0.5) * np.minimum(1, (t[-1] - t) / 0.2)
    add(sfx, drone, 32.5)
    for b in (34, 36, 38, 39):
        hb = kick() * 0.5
        add(sfx, filt(hb, 160, "low"), b, 1.0); add(sfx, filt(hb, 160, "low"), b + 0.42, 0.7)
    # ---- hits in the picture
    for b, big in ((18.5, 0.3), (19.0, 0.7), (21.0, 1.0), (23.0, 0.5), (24.0, 0.8), (30.0, 1.4)):
        add(sfx, punch(big), b, 0.75 + 0.2 * big)
    # whooshes one beat before the heavy ones
    for b in (17.2, 20.3, 22.3, 29.2):
        n_w = int(0.75 * BEAT * SR); t = np.arange(n_w) / n_w
        w = filt(rng.normal(0, 1, n_w), [500, 2500], "band") * np.sin(np.pi * t) ** 2 * 0.22
        add(sfx, w, b)
    lead = reverb(lead, 1.2, 0.25)
    mix = drums * 0.85 + mus * 0.8 + lead * 0.6 + reverb(sfx, 1.0, 0.18)
    # hard cut at 32 (keep only the reverb tail of the last bar)
    i32, i40 = int(32 * BEAT * SR), int(40 * BEAT * SR)
    tail = np.exp(-np.arange(i40 - i32) / (SR * 0.25))
    keep = sfx.copy(); keep[:i32] = 0; keep[i40:] = 0
    mix[i32:i40] = mix[i32:i40] * tail * 0.5 + reverb(keep, 1.0, 0.18)[i32:i40]
    # end fade
    i52 = int(49 * BEAT * SR)
    mix[i52:] *= np.linspace(1, 0, len(mix) - i52) ** 1.5
    mix = np.tanh(mix * 1.15)
    mix /= np.abs(mix).max() * 1.05
    return mix


def main(path):
    m = build()
    st = np.stack([m, np.roll(m, 23) * 0.98], 1)
    pcm = (st * 32767).astype("<i2")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print("wrote", path, round(len(m) / SR, 2), "s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "render", "strelka_track.wav"))
