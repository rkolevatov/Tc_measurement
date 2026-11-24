import pandas as pd
import time
import threading
import datetime
import numpy as np
import sys, os

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QCheckBox

import pyqtgraph as pg

from lcr1100 import LCR1100
from lakeshore import Lakeshore


pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')


# ======================================================================
#   AUTOMATED TEMPERATURE STEPPING ROUTINE (UP then DOWN)
# ======================================================================
# ======================================================================
#   AUTOMATED TEMPERATURE STEPPING ROUTINE (COOL DOWN only)
# ======================================================================
def temp_step_cooldown(lakeshore, start_T=0.900, stop_T=0.750, step=0.010,
                       mode_cb=None, tol=0.005, dwell_sec=60):
    """
    Cool DOWN from start_T to stop_T in 'step' decrements.

    At each step:
        • Wait for the temperature to reach ±tol of the setpoint
        • Then wait dwell_sec

    mode_cb(mode_str) is called with "cooling".
    """
    print("Starting temperature cool-down routine…")
    print(f"Initial T = {start_T:.4f} K")
    print(f"Final T   = {stop_T:.4f} K")
    print(f"Step      = {step*1000:.0f} mK")

    lakeshore.set_range(6)
    lakeshore.set_ramp()

    # Build COOLING step list: start_T, start_T-step, ..., stop_T
    cool_steps = []
    T = start_T
    while T > stop_T - 1e-9:
        cool_steps.append(round(T, 3))
        T -= step

    print("Cooling plan:", cool_steps)

    for target in cool_steps:
        if mode_cb is not None:
            mode_cb("cooling")

        print(f"\n=== COOLING: Setting SP = {target:.3f} K ===")
        lakeshore.set_point(target)

        # Wait for stability
        while True:
            try:
                T_now = float(lakeshore.sensor_temp_reading("A"))
            except Exception:
                T_now = None

            if T_now is not None:
                print(f"T = {T_now:.4f} K (target {target:.3f})")
                if abs(T_now - target) < tol:
                    print(f"Temperature stabilized. Waiting {dwell_sec} seconds…")
                    break

            time.sleep(1)

        time.sleep(dwell_sec)

    print("\nTemperature cool-down finished.")
    lakeshore.set_range_off()
    lakeshore.set_ramp_off()
    print("Heater off. Sequence complete.")


# ======================================================================
#   MAIN GUI APPLICATION
# ======================================================================
class Plots(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)

        self.setGeometry(0, 0, 1200, 1000)

        # ---------------------------
        # User-tunable robustness knobs
        # ---------------------------
        self.POLL_MS = 1000
        self.LCR_RETRIES = 3
        self.LCR_RETRY_SLEEP_S = 0.15
        self.MAX_PLOT_POINTS = 20000     # cap memory; increase if you want
        self.ERR_PRINT_COOLDOWN_S = 10.0 # avoid traceback spam

        # Instruments
        self.lcr = LCR1100()
        self.lakeshore = Lakeshore()

        # Data buffer: store [t, X]
        self.meas_data = np.empty((0, 2))

        # Shared state for warming/cooling label
        self._mode_lock = threading.Lock()
        self.temp_mode = "cooling"  # updated by heater thread

        # Error throttling
        self._last_err_time = {}

        self._widgets()
        self._layout()
        self.show()

        # Store timestamp for run folder naming (local time, no timezone math)
        self.t_start_local = time.time()

        self._is_running = False

    # ------------------------------------------------------------------
    def _widgets(self):
        self.plot = SimplePlotWidget()
        self.plot.set_title('Reactance')
        self.plot.set_ylabel('Reactance', '\u03A9')
        self.plot.add_curve('Reactance')
        self.plot.grid()

        self.start_button = QtWidgets.QPushButton('Start')
        self.start_button.clicked.connect(self.start_plotting)

        self.stop_button = QtWidgets.QPushButton('Stop')
        self.stop_button.clicked.connect(self.stop_plotting)

        self.checkbox = QCheckBox('Write to file')

    # ------------------------------------------------------------------
    def _layout(self):
        grid = QtWidgets.QGridLayout()
        grid.addWidget(self.plot, 0, 0, 1, 3)
        grid.addWidget(self.start_button, 1, 0)
        grid.addWidget(self.stop_button, 1, 1)
        grid.addWidget(self.checkbox, 1, 2)
        self.central_widget.setLayout(grid)

    # ------------------------------------------------------------------
    def _set_temp_mode(self, mode: str):
        with self._mode_lock:
            self.temp_mode = mode

    def _get_temp_mode(self) -> str:
        with self._mode_lock:
            return self.temp_mode

    # ------------------------------------------------------------------
    def _log_throttled(self, key: str, msg: str):
        now = time.time()
        last = self._last_err_time.get(key, 0.0)
        if (now - last) >= self.ERR_PRINT_COOLDOWN_S:
            print(msg)
            self._last_err_time[key] = now

    # ------------------------------------------------------------------
    def _safe_lcr_query(self):
        """
        Returns (R, X) or (nan, nan) if the instrument glitches.
        Retries a few times to avoid crashing the GUI.
        """
        for attempt in range(1, self.LCR_RETRIES + 1):
            try:
                R, X = self.lcr.query(5, 0.050)
                # guard against weird returns
                if R is None or X is None:
                    raise ValueError("LCR returned None")
                Rf = float(R)
                Xf = float(X)
                return Rf, Xf
            except Exception as e:
                self._log_throttled(
                    "lcr",
                    f"[LCR] query failed (attempt {attempt}/{self.LCR_RETRIES}): {type(e).__name__}: {e}"
                )
                time.sleep(self.LCR_RETRY_SLEEP_S)

        return np.nan, np.nan

    # ------------------------------------------------------------------
    def _safe_temp_read(self):
        try:
            return float(self.lakeshore.sensor_temp_reading("A"))
        except Exception as e:
            self._log_throttled("ls", f"[Lakeshore] read failed: {type(e).__name__}: {e}")
            return np.nan

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def start_plotting(self):
        if self._is_running:
            return
        self._is_running = True

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(self.POLL_MS)

        T0 = 0.75  # final temperature
        T_start = 0.90  # starting temperature = 900 mK

        heater_thread = threading.Thread(
            target=temp_step_cooldown,
            args=(self.lakeshore, T_start, T0, 0.010),
            kwargs={"mode_cb": self._set_temp_mode, "dwell_sec": 60},
            daemon=True
        )
        heater_thread.start()

    # ------------------------------------------------------------------
    def stop_plotting(self):
        if hasattr(self, "timer"):
            self.timer.stop()
        self._is_running = False

    # ------------------------------------------------------------------
    def update_plot(self):
        # LCR measurement (robust)
        R, X = self._safe_lcr_query()

        # Temperature measurement (robust)
        T = self._safe_temp_read()

        # Timestamp for plotting and CSV
        t = time.time()
        t_output = datetime.datetime.fromtimestamp(t).strftime("%m/%d/%y\n%H:%M:%S")

        # Update plot buffer
        self.meas_data = np.append(self.meas_data, np.array([[t, X]]), axis=0)

        # Cap memory so long runs don't explode
        if self.meas_data.shape[0] > self.MAX_PLOT_POINTS:
            self.meas_data = self.meas_data[-self.MAX_PLOT_POINTS:, :]

        self.plot.set_data('Reactance', self.meas_data)

        # CSV writing (with Mode column)
        if self.checkbox.isChecked():
            mode = self._get_temp_mode()  # "warming" or "cooling"

            t_local = datetime.datetime.fromtimestamp(self.t_start_local)
            dt_string = t_local.strftime("%Y-%m-%d_%H-%M-%S")

            path = f"output/Sample_A/{dt_string}"
            os.makedirs(path, exist_ok=True)

            csv_path = f"{path}/Sample_B.csv"
            columns = ['Date', 'Reactance [Ω]', 'Resistance [Ω]', 'Temperature [K]', 'Mode']
            row = [t_output, X, R, T, mode]

            df = pd.DataFrame([row], columns=columns)

            if not os.path.exists(csv_path):
                df.to_csv(csv_path, index=False)
            else:
                df.to_csv(csv_path, mode='a', header=False, index=False)


# ======================================================================
#   Plotting Helper Classes
# ======================================================================
class SimplePlotWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.curves = {}
        self.pens = iter([
            pg.mkPen(color='#1b9e77', width=2),
            pg.mkPen(color='#d95f02', width=2),
            pg.mkPen(color='#7570b3', width=2)
        ])
        self._plot()
        self._layout()

    def _plot(self):
        self.pg1 = pg.GraphicsLayoutWidget()
        self.plt1 = self.pg1.addPlot(
            row=1, col=1, title='',
            axisItems={'bottom': TimeAxisItem(orientation='bottom')}
        )
        self.plt1.setMenuEnabled(enableMenu=True)

    def _layout(self):
        vbox = QtWidgets.QVBoxLayout()
        vbox.addWidget(self.pg1)
        self.setLayout(vbox)

    def add_curve(self, crv_name):
        self.curves[crv_name] = self.plt1.plot(name=crv_name)
        self.curves[crv_name].setPen(next(self.pens))

    def set_title(self, title):
        self.plt1.setTitle(title)

    def set_ylabel(self, label, units=None):
        self.plt1.setLabel('left', label, units)

    def grid(self, x=True, y=True):
        self.plt1.showGrid(x=x, y=y)

    @QtCore.pyqtSlot()
    def set_data(self, crv_name, data):
        # data is Nx2 array (t, y)
        self.curves[crv_name].setData(data[:, 0], data[:, 1])


class TimeAxisItem(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def tickStrings(self, values, scale, spacing):
        return [self.int2dt(v).strftime("%m/%d/%y\n%H:%M:%S") for v in values]

    def int2dt(self, ts):
        return datetime.datetime.fromtimestamp(float(ts))  # local time, no offset


# ======================================================================
#   MAIN APP
# ======================================================================
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = Plots()
    window.show()
    sys.exit(app.exec_())
