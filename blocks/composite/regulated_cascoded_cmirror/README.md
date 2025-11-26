## Team Mahowalders Open-Source Silicon Project, Chipathon 2025
### Project: Towards Precision Current Mirrors

![](./_images/Full.jpg)  
![](./_images/Top.png)  

**Motivation:** With the rise of analog computation for low-power edge intelligence and sensor systems, the demand for robust bias generation circuits has significantly increased. Bias current sources are fundamental to analog and mixed-signal designs, enabling precise control in amplifiers, comparators, sensor front-ends, and a wide range of other analog building blocks. Ideally, current sources deliver a quasi-constant current when transistors operate in the saturation region, where the output current is largely independent of the drain-to-source voltage. Achieving bias current sources that closely approximate this ideal behaviour is essential to ensure proper circuit operation. However, traditional current mirrors, though widely used, exhibit poor output impedance and limited voltage headroom, which can result in unstable biasing under varying conditions. When the output voltage exceeds the linear range, the current mirror output continues to increase linearly in the saturation region instead of reaching a plateau. This non-ideal behaviour makes such mirrors unsuitable for delivering stable bias currents, often leading to degraded performance in circuits that rely on precise biasing.

**Objective:** This project proposes the automated design and layout of a high-impedance, energy-efficient bias generation block using regulated current mirror architectures. Integrated into the gLayout toolchain (Python2GDS), this design aims to enhance layout portability, stability, and scalability across process corners.

**Design:**  
We compare three bias current mirror architectures: 

* Vanilla Current Mirror (VCM), as a reference  
* Self-Biased Common-Source CM (SB-CM), with improved impedance, moderate complexity  
* Regulated Cascode CM (RC-CM), with high output impedance, better stability, but requires auxiliary bias

All three versions will be parametrically instantiated via gLayout, enabling on-demand generation and automated layout. A testbench OTA stage will be used to convert an input voltage into current, allowing characterisation of each mirror’s response and stability under load.

**Contributions:** 

* gLayout-compatible IP blocks for advanced analog biasing  
* On-silicon testing of all three architectures, with a focus on RC-CM  
* Performance benchmarking and trade-off analysis (stability, impedance, layout area, and bias dependencies)

**Applications:**  
The proposed IP targets analog designs where stable biasing is critical, such as sensor front-ends, neural interface systems, and low-frequency amplifiers. The RC-CM in particular can significantly improve performance in circuits sensitive to bias drift, without requiring extensive overhead. The regulated cascode current mirror provides a more robust stable current source than vanilla current mirrors that are usually used as is in analog circuits using biasin. By using this improved version, a wide range of analog circuits applications such as bias current generators, op-amps or sensor front-end where stable and accurate biasing is crucial to ensure the expected functioning of the circuit can benefit from the improved current mirror.

### **Full Design Schematic:**  

![](./_images/finalS.png) 

## 📐 Detailed Description of the Current Mirror Schematic

This schematic illustrates a **high-performance, multi-output current mirroring system** designed for precision analog applications. The design centers on replicating and regulating an input current, utilizing a reference bias network to set the operational parameters for three distinct current mirror topologies. 

[Image of Current Mirror Circuit Diagram]


---

### Input and Bias Network

* **Inputs:** The circuit accepts several primary inputs:
    * **VDD:** The main power supply rail.
    * **EN (Enable):** A digital control signal to power-gate the entire system.
    * **V\_IN:** The primary **Analog Input** voltage or current source that the system is designed to replicate.
    * **V\_AUX\_CCM:** An auxiliary analog input specifically used to establish the control voltage for the **Regulated Cascode Current Mirror**.
* **Bias Generation (1/1000x Bias):** A dedicated sub-circuit generates a highly stable, low-current **reference bias** ($\text{bias\_out}$). This reference current is scaled (indicated as $1/1000\times$) and distributed to set the accurate operational point for all three current mirror stages, ensuring robust current matching and temperature stability.

---

### Current Distribution Array (Top Section)

The components connected to the VDD and EN lines, labeled with instances like $\text{R}M\text{K}1$ through $\text{R}M\text{K}5$, form a current distribution or steering array. This section likely consists of matched transistors and resistors ($1 \times 10.0\Omega / 2.0\text{u}$ and $1 \times 10.0\Omega / 2.0\text{u}$ labels) that use **V\_IN** and the main current path to generate the input currents for the mirroring stages below. The matching of these components is crucial for the subsequent accuracy of the mirrored currents.

---

### Parallel Current Mirror Stages

The design incorporates three parallel current mirror blocks, each providing a different level of performance and complexity:

1.  **Vanilla Current Mirror ($\text{vanilla\_cm}$):**
    * **Function:** This is the most basic implementation, providing a simple, proportional replication of the input current.
    * **Output:** **V\_OUT\_VCM**.
    * **Characteristics:** Moderate output impedance and matching, suitable where lower complexity is prioritized.

2.  **Self-Biased Current Mirror ($\text{biased\_cm}$):**
    * **Function:** Features an internal feedback mechanism (self-biasing) to make the output current more immune to variations in the supply voltage (**VDD**) and less sensitive to transistor channel length modulation.
    * **Output:** **V\_OUT\_BCM**.
    * **Characteristics:** Improved current regulation and better current matching compared to the Vanilla type.

3.  **Regulated Cascode Current Mirror ($\text{cascode\_cm}$):**
    * **Function:** This is the highest-precision stage. It uses a cascode transistor driven by an operational amplifier (or similar regulating circuit, potentially fed by **V\_AUX\_CCM**) to create an extremely high output impedance.
    * **Output:** **V\_OUT\_CCM**.
    * **Characteristics:** Provides the **highest accuracy** and regulation of the mirrored current, minimizing the impact of load voltage changes.

---

### Outputs

The circuit provides four outputs:

* **V\_OUT\_VIN:** This output appears to be a buffered or regulated version of the original input **V\_IN**.
* **V\_OUT\_VCM:** Output from the Vanilla Current Mirror.
* **V\_OUT\_BCM:** Output from the Self-Biased Current Mirror.
* **V\_OUT\_CCM:** Output from the Regulated Cascode Current Mirror.

---

Would you like a separate section for your Readme detailing the pin-out table and pin functionalities?

### **Block: Vanilla Current Mirror (VCM)**  
![](./_images/vcm.png)  
A classical current mirror consists of two transistors: the first Q20 has its drain and gate connected (forming a diode-connected structure) and receives the input current, while the second transistor Q21 mirrors this current at its output. The output current is ideally a scaled replica of the input, determined by the ratio of the transistors' width-to-length (W/L) dimensions.

### **Block: Self-biased Common Source Current Mirror**  
![](./_images/sbcm.png)  
The self-biased common-source current mirror uses a feedback mechanism to improve current stability and output impedance. Q22 receives the reference current through a diode connection, setting the gate voltage shared with Q24, which mirrors the current. Q23 and Q25, connected in a common-source configuration, form a self-biasing loop that regulates the source voltage of the upper transistors. This feedback stabilises the gate-source voltage, reducing output current variation and enhancing performance compared to a basic current mirror.

### **Block: Regulated Cascoded Current Mirror**  
![](./_images/rccm.png)  
The regulated cascode current mirror shown uses an auxiliary biasing loop to significantly boost output impedance and current stability. Q26 and Q27 form a standard current mirror, while Q28 and Q30 act as cascode transistors, shielding the mirroring devices from output voltage swings. Q29 senses the drain voltage of Q28 and regulates it via Q31, creating a feedback loop that stabilizes the cascode node. This regulation ensures minimal variation in output current despite changes in output voltage, making the design ideal for precision analog applications demanding high output resistance and improved bias accuracy.

### **Diagram: Top Integration and Expected Behaviour:**   
![](./_images/tops.png)  
![](./_images/sim.png)  
 

### **Pinlist:**

|  Pin No (in Padframe): | Pin Name | Pin Type | Direction | Group | GF180mcu Cell |
|---|:----------|:-----------|:--------------|:---------------|:------------------------|
| 47| VSS       | Ground     | Bidirectional | A3 Mahowalders | gr180mcu_fd_io_dvss     |
| 48| VCM_OUT   | Analog     | Output        | A3 Mahowalders | gr180mcu_fd_io_asig_5p0 |
| 49| BCM_OUT   | Analog     | Output        | A3 Mahowalders | gr180mcu_fd_io_asig_5p0 |
| 50| CCM_OUT   | Analog     | Output        | A3 Mahowalders | gr180mcu_fd_io_asig_5p0 |
| 51| V_BIAS_IN | Analog     | Output        | A3 Mahowalders | gr180mcu_fd_io_asig_5p0 |
| 52| EN        | Digital    | Input         | A3 Mahowalders | gr180mcu_fd_io_in_c     |
| 53| V_AUX     | Analog     | Input         | A3 Mahowalders | gr180mcu_fd_io_asig_5p0 |
| 54| V_IN      | Analog     | Input         | A3 Mahowalders | gr180mcu_fd_io_asig_5p0 |
| 55| VSS       | Ground     | Bidirectional | A3 Mahowalders | gr180mcu_fd_io_dvss     |
| 56| VDD_3V3   | 3V Power   | Bidirectional | A3 Mahowalders | gr180mcu_fd_io_dvd       |
#### **Layout:** 

![](./_images/l1.png)  
![](./_images/l2.png)
![](./_images/l3.png)  
![](./_images/l4.png)


### **Current Status:**
![](./_images/status.png) 

### Reference:

1. Michal, Vratislav. "Regulated Cascode Current Mirror with Improved Voltage Swing." 2022 International Conference on Applied Electronics (AE). IEEE, 2022\. DOI : 10.1109/AE54730.2022.9920096  
2. Garde, M. Pilar, et al. "Wide-Swing Class AB Regulated Cascode Current Mirror." *2020 IEEE International Symposium on Circuits and Systems (ISCAS)*. IEEE, 2020\.  
3. Pretl, Harald, and Matthias Eberlein. "Fifty nifty variations of two-transistor circuits: A tribute to the versatility of MOSFETs." *IEEE Solid-State Circuits Magazine* 13.3 (2021): 38-46 and *references therein*  
4. GF180 PadFrame Document: [PADFrame \- Chipathon 2023](https://docs.google.com/presentation/d/12w4WBoleFAE4UePdoUf-bxsZR_BttwY3wknBPPJrEHE/edit?usp=sharing)
