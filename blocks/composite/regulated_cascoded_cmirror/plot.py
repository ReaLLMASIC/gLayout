import numpy as np
import matplotlib.pyplot as plt

path = "/headless/.xschem/simulations"

# Load the saved sweeps
v1, i1 = np.loadtxt(path + '/vanilla.txt', unpack=True)
v2, i2 = np.loadtxt(path + '/biased.txt', unpack=True)
v3, i3 = np.loadtxt(path + '/cascode.txt', unpack=True)

plt.plot(v1, i1, label="Vanilla")
plt.plot(v2, i2, label="Biased")
plt.plot(v3, i3, label="Cascode")

plt.xlabel("V_out (V)")
plt.ylabel("I_out (A)")
plt.title("I-V Curves of Different Current Mirrors")
plt.legend()
plt.grid(True)
plt.show()
