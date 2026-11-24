import time
import serial


class Lakeshore:
    """
    Correct Lakeshore 372 Control Class
    with stable RuOx configuration.
    """

    port = "/dev/ttyUSB4"
    baud = 57600

    def __init__(self):
        self.serial = serial.Serial(
            Lakeshore.port,
            Lakeshore.baud,
            serial.SEVENBITS,
            serial.PARITY_ODD,
            stopbits=1,
            timeout=1
        )

        # ===============================
        # Identify instrument
        # ===============================
        self.write("*IDN?")
        print(self.read())

        # ===============================
        # Configure INPUT A (RuOx thermistor)
        # ===============================
        #
        # INTYPE A, <excitation mode>, <excitation val>, <autorange>,
        #            <range>, <shunt>, <units>
        #
        #  - excitation mode 1 = current excitation (correct for RuOx)
        #  - excitation value 1 = use nominal current
        #  - autorange 1 = ON
        #  - range 0 = AUTO
        #  - shunt 0 = none
        #  - units 1 = Kelvin
        #
        self.write("INTYPE A,1,1,1,0,0,1")
        time.sleep(0.3)

        # ===============================
        # Assign RuOx calibration curve 21
        # ===============================
        self.write("INCRV A,21")
        time.sleep(0.3)

        # ===============================
        # REQUIRED for 372 inputs:
        # Enable input A
        # (prevents curve from dropping during autorange transitions)
        # ===============================
        self.write("INSET A,1")
        time.sleep(0.3)

        # Confirm curve assignment
        self.write("INCRV? A")
        print("Curve A =", self.read())

    # ======================================================
    # Low-level helpers
    # ======================================================
    def write(self, msg: str):
        """Send command with newline."""
        self.serial.write((msg + "\n").encode())

    def read(self) -> str:
        """Read until CR."""
        buf = b""
        while True:
            c = self.serial.read(1)
            if c in (b"", b"\r"):
                break
            buf += c
        return buf.decode(errors="ignore")

    # ======================================================
    # Temperature & resistance
    # ======================================================
    def sensor_temp_reading(self, channel="A"):
        """
        Read temperature in Kelvin using KRDG?.
        Automatic retry to avoid autorange glitch.
        """
        for attempt in range(3):
            self.write(f"KRDG? {channel}")
            try:
                val = float(self.read())
                # Guard against numeric explosions
                if 0.00001 < val < 50.0:
                    return val
            except:
                pass
            time.sleep(0.1)

        return float("nan")

    def sensor_res_reading(self, channel="A"):
        """Read raw resistance (Ohms)."""
        self.write(f"RDGR? {channel}")
        try:
            return float(self.read())
        except:
            return float("nan")

    # ======================================================
    # Heater control (372 syntax)
    # ======================================================
    def set_point(self, T):
        """Set temperature setpoint for loop 0."""
        self.write(f"SETP 0,{T}")
        time.sleep(0.2)

    def set_ramp(self, rate=0.1):
        """Enable loop ramp at <rate> K/min."""
        self.write(f"RAMP 0,1,{rate}")
        time.sleep(0.2)

    def set_ramp_off(self):
        """Disable ramp."""
        self.write("RAMP 0,0,0")
        time.sleep(0.2)

    def set_range(self, r):
        """Set heater range for loop 0."""
        self.write(f"RANGE 0,{r}")
        time.sleep(0.2)

    def set_range_off(self):
        """Turn heater off."""
        self.write("RANGE 0,0")
        time.sleep(0.2)


# ======================================================
# Standalone test
# ======================================================
if __name__ == "__main__":
    dev = Lakeshore()

    print("Temp A =", dev.sensor_temp_reading("A"))
    print("Res  A =", dev.sensor_res_reading("A"))
