"""
PPG Real-Time Heart Rate Monitor
=================================
Reads AC samples from a serial port (or replays an ODS file for testing),
applies a bandpass filter + sliding-window autocorrelation, and displays:
  • Live PPG waveform (raw + filtered)
  • Beat-to-beat BPM trend
  • Large BPM readout with confidence indicator
  • START button  – begins data acquisition and plotting
  • STOP button   – halts acquisition, resets all data and plots

Usage
-----
  # Live mode  (UART @ 200 Hz, one int16 per line)
  python ppg_realtime.py --port /dev/ttyUSB0 --baud 115200

  # Replay mode  (simulate live feed from ODS file)
  python ppg_realtime.py --replay data.ods

  # Replay at a custom speed multiplier (e.g. 2x faster)
  python ppg_realtime.py --replay data.ods --speed 2

Dependencies
------------
  pip install numpy scipy matplotlib pandas pyserial odfpy openpyxl

Firmware assumptions
--------------------
  fs = 200 Hz  (5 ms sampling interval)
  SHIFT = 6    -> HPF cutoff ~0.50 Hz (below cardiac band floor of 0.7 Hz)
  UART format: one signed integer per line, e.g. "-42\n"
  Col 0 of the ODS file is the raw ADC channel (higher amplitude, better SNR).
"""

import argparse
import collections
import sys
import threading
import time

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button
from scipy.signal import butter, filtfilt, find_peaks

# ── constants ────────────────────────────────────────────────────────────────
FS          = 200
BPF_LO      = 0.7
BPF_HI      = 3.5
BPF_ORDER   = 4
WIN_SEC     = 4
HOP_SEC     = 0.5
DISP_SEC    = 8
BPM_MIN     = 40
BPM_MAX     = 180
CONF_THRESH = 0.15
BPM_HISTORY = 30

C = {
    "raw":             "#378add",
    "filtered":        "#1d9e75",
    "peaks":           "#ef9f27",
    "bpm_line":        "#e24b4a",
    "bg":              "#0e1117",
    "panel":           "#1a1f2e",
    "text":            "#e0e4ef",
    "subtext":         "#8892aa",
    "conf_ok":         "#1d9e75",
    "conf_low":        "#ef9f27",
    "conf_bad":        "#e24b4a",
    "btn_start_on":    "#1d9e75",
    "btn_start_hover": "#25c48e",
    "btn_stop_on":     "#e24b4a",
    "btn_stop_hover":  "#ff6b6b",
    "btn_off":         "#2a2f45",
    "btn_txt":         "#e0e4ef",
}

# ── DSP helpers ───────────────────────────────────────────────────────────────
def make_bandpass(fs=FS):
    b, a = butter(BPF_ORDER,
                  [BPF_LO / (fs / 2), BPF_HI / (fs / 2)],
                  btype="band")
    return b, a


def autocorr_bpm(samples, fs=FS):
    """Return (bpm, confidence) or (None, 0.0) on failure."""
    if len(samples) < fs * 2:
        return None, 0.0
    b, a = make_bandpass(fs)
    try:
        x = filtfilt(b, a, samples)
    except Exception:
        return None, 0.0
    x -= x.mean()
    ac = np.correlate(x, x, mode="full")
    n  = len(x)
    ac = ac[n - 1:]
    if ac[0] == 0:
        return None, 0.0
    ac /= ac[0]
    lo_lag = int(fs * 60 / BPM_MAX)
    hi_lag = min(int(fs * 60 / BPM_MIN), len(ac) - 1)
    if lo_lag >= hi_lag:
        return None, 0.0
    lag = lo_lag + int(np.argmax(ac[lo_lag:hi_lag]))
    return fs * 60.0 / lag, float(ac[lag])


def detect_peaks(filtered, fs=FS):
    min_dist   = int(fs * 60 / BPM_MAX)
    prominence = np.std(filtered) * 0.4
    if prominence == 0:
        return np.array([], dtype=int)
    pks, _ = find_peaks(filtered, distance=min_dist, prominence=prominence)
    return pks


# ── data sources ──────────────────────────────────────────────────────────────
class SerialSource:
    """Reads one integer per line from a UART port in a background thread."""

    def __init__(self, port, baud):
        import serial
        self._ser    = serial.Serial(port, baud, timeout=1)
        self._q      = collections.deque()
        self._lock   = threading.Lock()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while True:
            try:
                line = self._ser.readline().decode("ascii", errors="ignore").strip()
                if line:
                    with self._lock:
                        self._q.append(int(line))
            except (ValueError, OSError):
                pass

    def drain(self):
        with self._lock:
            items = list(self._q)
            self._q.clear()
        return items

    def start(self):
        """Flush stale bytes that arrived while stopped."""
        with self._lock:
            self._q.clear()

    def reset(self):
        with self._lock:
            self._q.clear()


class ReplaySource:
    """
    Replays an ODS file at the correct sample rate.
    drain() returns [] until start() is called.
    reset() rewinds to the beginning.
    """

    def __init__(self, path, speed=1.0):
        import pandas as pd
        df = pd.read_excel(path, engine="odf", header=None)
        self._data     = df[0].dropna().values.astype(float)
        self._speed    = speed
        self._interval = 1.0 / (FS * speed)
        self._idx      = 0
        self._last_t   = None   # None = paused

    def start(self):
        self._last_t = time.perf_counter()

    def reset(self):
        self._idx    = 0
        self._last_t = None

    def drain(self):
        if self._last_t is None:
            return []
        now     = time.perf_counter()
        elapsed = now - self._last_t
        n       = int(elapsed / self._interval)
        if n == 0:
            return []
        self._last_t += n * self._interval
        end   = min(self._idx + n, len(self._data))
        chunk = self._data[self._idx:end].tolist()
        self._idx = end
        if self._idx >= len(self._data):
            self._idx = 0   # loop
        return chunk


# ── main application ──────────────────────────────────────────────────────────
class PPGMonitor:

    def __init__(self, source):
        self.source     = source
        self.fs         = FS
        self._measuring = False

        self._disp_len = int(DISP_SEC * FS)
        self._win_len  = int(WIN_SEC  * FS)
        self._hop_len  = int(HOP_SEC  * FS)
        self._b, self._a = make_bandpass(FS)

        self._reset_state()
        self._build_ui()

        self._anim = FuncAnimation(
            self.fig, self._update,
            interval=50,
            blit=False,
            cache_frame_data=False,
        )

    # ── state ─────────────────────────────────────────────────────────────────
    def _reset_state(self):
        self._raw_buf  = collections.deque([0.0] * self._disp_len,
                                           maxlen=self._disp_len)
        self._flt_buf  = collections.deque([0.0] * self._disp_len,
                                           maxlen=self._disp_len)
        self._all_raw  = collections.deque(maxlen=self._win_len)

        self._bpm_times  = collections.deque(maxlen=BPM_HISTORY)
        self._bpm_values = collections.deque(maxlen=BPM_HISTORY)
        self._bpm_confs  = collections.deque(maxlen=BPM_HISTORY)

        self._current_bpm  = None
        self._current_conf = 0.0
        self._hop_counter  = 0
        self._sample_count = 0

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        plt.style.use("dark_background")
        self.fig = plt.figure(figsize=(13, 8), facecolor=C["bg"])
        self.fig.canvas.manager.set_window_title("PPG Heart Rate Monitor")

        # plots occupy the top 80 %; bottom 18 % is the button strip
        gs = gridspec.GridSpec(
            2, 2,
            figure=self.fig,
            left=0.06, right=0.97,
            top=0.93,  bottom=0.18,
            hspace=0.45, wspace=0.3,
        )

        # waveform ────────────────────────────────────────────────────────────
        self.ax_wave = self.fig.add_subplot(gs[0, :])
        self._style_ax(self.ax_wave, "PPG Waveform", ylabel="ADC counts")
        self.ax_wave.grid(color="#2a2f45", linewidth=0.5)

        t = np.arange(self._disp_len) / FS - DISP_SEC
        self._ln_raw, = self.ax_wave.plot(
            t, list(self._raw_buf),
            color=C["raw"], lw=0.8, alpha=0.5, label="raw")
        self._ln_flt, = self.ax_wave.plot(
            t, list(self._flt_buf),
            color=C["filtered"], lw=1.4, label="filtered")
        self._sc_peaks = self.ax_wave.scatter(
            [], [], color=C["peaks"], s=50, zorder=5, label="beat")
        self.ax_wave.set_xlim(-DISP_SEC, 0)
        self.ax_wave.set_xlabel("time (s)", color=C["subtext"], fontsize=9)
        self.ax_wave.legend(loc="upper left", fontsize=8,
                            facecolor=C["panel"], edgecolor="none",
                            labelcolor=C["text"])

        # idle overlay
        self._idle_text = self.ax_wave.text(
            0.5, 0.5,
            "Press   \u25b6  START   to begin measurement",
            ha="center", va="center",
            transform=self.ax_wave.transAxes,
            fontsize=14, color=C["subtext"], style="italic",
            bbox=dict(boxstyle="round,pad=0.5",
                      facecolor=C["panel"], edgecolor="none", alpha=0.88),
        )

        # BPM trend ───────────────────────────────────────────────────────────
        self.ax_bpm = self.fig.add_subplot(gs[1, 0])
        self._style_ax(self.ax_bpm, "BPM Trend", ylabel="BPM")
        self.ax_bpm.set_ylim(40, 180)
        self.ax_bpm.grid(color="#2a2f45", linewidth=0.5)
        self._ln_bpm, = self.ax_bpm.plot(
            [], [], color=C["bpm_line"], lw=1.8,
            marker="o", markersize=4, markerfacecolor=C["bpm_line"])
        self.ax_bpm.set_xlabel("window", color=C["subtext"], fontsize=9)

        # numeric readout ─────────────────────────────────────────────────────
        self.ax_num = self.fig.add_subplot(gs[1, 1])
        self.ax_num.set_facecolor(C["panel"])
        self.ax_num.set_axis_off()

        self._txt_bpm = self.ax_num.text(
            0.5, 0.58, "---",
            ha="center", va="center", transform=self.ax_num.transAxes,
            fontsize=64, fontweight="bold", color=C["text"],
            fontfamily="monospace")
        self.ax_num.text(
            0.5, 0.24, "BPM",
            ha="center", va="center", transform=self.ax_num.transAxes,
            fontsize=16, color=C["subtext"])
        self._txt_conf = self.ax_num.text(
            0.5, 0.10, "press START to measure",
            ha="center", va="center", transform=self.ax_num.transAxes,
            fontsize=9, color=C["subtext"])
        self._rect_conf = plt.Rectangle(
            (0.1, 0.02), 0.0, 0.04,
            transform=self.ax_num.transAxes,
            color=C["conf_ok"], zorder=2)
        self.ax_num.add_patch(self._rect_conf)

        # buttons ─────────────────────────────────────────────────────────────
        btn_w, btn_h = 0.15, 0.07
        gap          = 0.06
        cx           = 0.5
        y0           = 0.055

        ax_s = self.fig.add_axes([cx - btn_w - gap / 2, y0, btn_w, btn_h])
        ax_e = self.fig.add_axes([cx + gap / 2,         y0, btn_w, btn_h])

        self._btn_start = Button(ax_s, "\u25b6  START",
                                 color=C["btn_start_on"],
                                 hovercolor=C["btn_start_hover"])
        self._btn_stop  = Button(ax_e, "\u25a0  STOP",
                                 color=C["btn_off"],
                                 hovercolor=C["btn_stop_on"])

        for btn, col in [(self._btn_start, C["btn_txt"]),
                         (self._btn_stop,  C["subtext"])]:
            btn.label.set_fontsize(11)
            btn.label.set_fontweight("bold")
            btn.label.set_color(col)

        self._btn_start.on_clicked(self._on_start)
        self._btn_stop.on_clicked(self._on_stop)

    @staticmethod
    def _style_ax(ax, title, ylabel=""):
        ax.set_facecolor(C["panel"])
        ax.set_title(title, color=C["text"], fontsize=11, pad=6)
        if ylabel:
            ax.set_ylabel(ylabel, color=C["subtext"], fontsize=9)
        ax.tick_params(colors=C["subtext"], labelsize=8)
        for sp in ax.spines.values():
            sp.set_color(C["panel"])

    # ── button callbacks ──────────────────────────────────────────────────────
    def _on_start(self, _event):
        if self._measuring:
            return
        self._measuring = True

        # START button goes dim; STOP button lights up
        self._btn_start.color      = C["btn_off"]
        self._btn_start.hovercolor = C["btn_off"]
        self._btn_start.label.set_color(C["subtext"])
        self._btn_stop.color       = C["btn_stop_on"]
        self._btn_stop.hovercolor  = C["btn_stop_hover"]
        self._btn_stop.label.set_color(C["btn_txt"])

        self._idle_text.set_visible(False)
        self._reset_state()
        self.source.start()
        self.fig.canvas.draw_idle()
        print("[ppg] Measurement started")

    def _on_stop(self, _event):
        if not self._measuring:
            return
        self._measuring = False

        self.source.reset()
        self._reset_state()
        self._clear_plots()
        self._idle_text.set_visible(True)

        # STOP button goes dim; START button lights up
        self._btn_start.color      = C["btn_start_on"]
        self._btn_start.hovercolor = C["btn_start_hover"]
        self._btn_start.label.set_color(C["btn_txt"])
        self._btn_stop.color       = C["btn_off"]
        self._btn_stop.hovercolor  = C["btn_stop_on"]
        self._btn_stop.label.set_color(C["subtext"])

        self.fig.canvas.draw_idle()
        print("[ppg] Measurement stopped and reset")

    def _clear_plots(self):
        zeros = [0.0] * self._disp_len
        self._ln_raw.set_ydata(zeros)
        self._ln_flt.set_ydata(zeros)
        self._sc_peaks.set_offsets(np.empty((0, 2)))
        self.ax_wave.set_ylim(-1, 1)

        self._ln_bpm.set_data([], [])
        self.ax_bpm.set_ylim(40, 180)
        self.ax_bpm.set_xlim(-0.5, BPM_HISTORY - 1)

        self._txt_bpm.set_text("---")
        self._txt_bpm.set_color(C["text"])
        self._txt_conf.set_text("press START to measure")
        self._txt_conf.set_color(C["subtext"])
        self._rect_conf.set_width(0)

    # ── animation ─────────────────────────────────────────────────────────────
    def _update(self, _frame):
        if not self._measuring:
            return

        new = self.source.drain()
        if not new:
            return

        self._all_raw.extend(new)
        for v in new:
            self._raw_buf.append(v)
            self._hop_counter  += 1
            self._sample_count += 1

        # bandpass the display buffer
        raw_arr = np.array(self._raw_buf, dtype=float)
        try:
            flt_arr = filtfilt(self._b, self._a, raw_arr)
        except Exception:
            flt_arr = np.zeros_like(raw_arr)
        self._flt_buf = collections.deque(flt_arr, maxlen=self._disp_len)

        # BPM every HOP_SEC
        if self._hop_counter >= self._hop_len:
            self._hop_counter = 0
            self._compute_bpm()

        # waveform
        flt_list = list(self._flt_buf)
        raw_list = list(self._raw_buf)
        self._ln_raw.set_ydata(raw_list)
        self._ln_flt.set_ydata(flt_list)

        combined = raw_list + flt_list
        if any(v != 0 for v in combined):
            mn, mx = min(combined), max(combined)
            pad = max((mx - mn) * 0.15, 1)
            self.ax_wave.set_ylim(mn - pad, mx + pad)

        flt_np = np.array(flt_list)
        peaks  = detect_peaks(flt_np, self.fs)
        t_axis = np.arange(self._disp_len) / self.fs - DISP_SEC
        if len(peaks):
            self._sc_peaks.set_offsets(
                np.column_stack([t_axis[peaks], flt_np[peaks]]))
        else:
            self._sc_peaks.set_offsets(np.empty((0, 2)))

        # BPM trend
        if self._bpm_values:
            xs = list(range(len(self._bpm_values)))
            ys = list(self._bpm_values)
            self._ln_bpm.set_data(xs, ys)
            self.ax_bpm.set_xlim(-0.5, max(xs[-1], BPM_HISTORY - 1) + 0.5)
            valid = [b for b in ys if b is not None]
            if valid:
                self.ax_bpm.set_ylim(max(40,  min(valid) - 10),
                                     min(180, max(valid) + 10))

        # numeric readout
        if self._current_bpm is not None:
            self._txt_bpm.set_text(f"{self._current_bpm:.0f}")
            conf = self._current_conf
            cw   = min(conf * 0.8, 0.8)
            self._rect_conf.set_width(cw)
            self._rect_conf.set_x(0.1)
            if conf >= 0.5:
                col, lbl = C["conf_ok"],  f"confidence  {conf:.2f}  \u2713"
            elif conf >= CONF_THRESH:
                col, lbl = C["conf_low"], f"confidence  {conf:.2f}  ~"
            else:
                col, lbl = C["conf_bad"], f"confidence  {conf:.2f}  \u2717"
            self._rect_conf.set_color(col)
            self._txt_conf.set_text(lbl)
            self._txt_bpm.set_color(col)

    def _compute_bpm(self):
        buf = np.array(self._all_raw, dtype=float)
        if len(buf) < self._win_len:
            return
        bpm, conf = autocorr_bpm(buf[-self._win_len:], self.fs)
        if bpm is None or conf < CONF_THRESH:
            return
        self._bpm_times.append(self._sample_count / self.fs)
        self._bpm_values.append(round(bpm, 1))
        self._bpm_confs.append(conf)
        self._current_bpm  = bpm
        self._current_conf = conf

    def run(self):
        plt.show()


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(
        description="Real-time PPG heart rate monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--port",   metavar="PORT",
                      help="Serial port, e.g. /dev/ttyUSB0 or COM3")
    mode.add_argument("--replay", metavar="FILE",
                      help="ODS file to replay (uses col 0, raw ADC)")
    p.add_argument("--baud",  type=int,   default=115200)
    p.add_argument("--speed", type=float, default=1.0,
                   help="Replay speed multiplier (default: 1.0)")
    return p.parse_args()


def main():
    args = parse_args()

    if args.port:
        try:
            src = SerialSource(args.port, args.baud)
            print(f"[ppg] Ready on {args.port} @ {args.baud} baud  -- press START")
        except Exception as e:
            sys.exit(f"[ppg] Cannot open serial port: {e}")
    else:
        try:
            src = ReplaySource(args.replay, speed=args.speed)
            print(f"[ppg] Loaded '{args.replay}' at {args.speed}x speed  -- press START")
        except Exception as e:
            sys.exit(f"[ppg] Cannot open replay file: {e}")

    PPGMonitor(src).run()


if __name__ == "__main__":
    main()