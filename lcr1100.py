import time
import numpy as np
import pandas as pd
import datetime
import os
import matplotlib.pyplot as plt

import serial


class LCR1100:
    port = "/dev/ttyUSB5"
    baud = 9600

    def __init__(self):
        self.serial = serial.Serial(
            LCR1100.port,
            LCR1100.baud,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5
        )

    def idn(self):
        return self.write("*IDN?")

    def write(self, command):
        self.serial.write((command + "\n").encode())

        c = ""
        s = ""

        c = self.serial.read(1)
        if c != b"":
            s += c.decode()
            while (c != b'\n'):
                c = self.serial.read(1)
                s += c.decode()
            return s
        else:
            return ""

    def query(self, FREQ, V):
        self.write("FUNC R-X\n")
        self.write("FREQ {}K".format(FREQ))
        self.write("LEV:VOLT {}\n".format(V))
        imp = self.write("FETC:IMP?")
        R = float(imp.split(",")[0])
        X = float(imp.split(",")[1])
        return R, X


if __name__ == "__main__":
    lcr = LCR1100()
    print(repr(lcr.idn()))
#     now = datetime.datetime.utcfromtimestamp(float(time.time() - (60.0 * 60.0 * 5.0)))
#     dt_string = now.strftime("%m-%d-%y %H:%M:%S")
#     path = "/home/dmradio/PycharmProjects/TeledyneT3LCR1100/" + dt_string
#
#     if not os.path.exists(path):
#         os.makedirs(path)
#
#     lcr = LCR1100()
#     lcr.write("FUNC R-X\n")
#     lcr.write("LEV:VOLT 0.3\n")
#
#     FREQs = np.linspace(1, 100, 100)
#     # FREQs = FREQs/100
#
#     Rs = []
#     Xs = []
#     for FREQ in FREQs:
#         lcr.write("FREQ {}K".format(FREQ))
#         time.sleep(2)
#         imp = lcr.write("FETC:IMP?")
#         R = float(imp.split(",")[0])
#         X = float(imp.split(",")[1])
#         print("Frequency {}kHz: R={:.3f} Ohms, X={:.3f} Ohms".format(FREQ, R, X))
#
#         Rs.append(R)
#         Xs.append(X)
#
#     dataRX = {
#         "Frequency [kHz]": FREQs,
#         "R [Ohms]": Rs,
#         "X [Ohms]": Xs
#     }
#
#     dfRX = pd.DataFrame.from_dict(dataRX)
#     dfRX.to_csv(path + "/dfRX.csv")
#
#     plt.plot(dataRX["Frequency [kHz]"], dataRX["R [Ohms]"])
#     plt.xlabel("Frequency [kHz]")
#     plt.ylabel("R [Ohms]")
#     plt.grid(True)
#     plt.savefig(path + "/R.pdf", bbox_inches="tight")
#     plt.clf()
#
#     plt.plot(dataRX["Frequency [kHz]"], dataRX["X [Ohms]"])
#     plt.xlabel("Frequency [kHz]")
#     plt.ylabel("X [Ohms]")
#     plt.grid(True)
#     plt.savefig(path + "/X.pdf", bbox_inches="tight")
#     plt.clf()
