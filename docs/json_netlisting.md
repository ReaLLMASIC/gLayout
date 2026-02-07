\# JSON-based Netlisting for Dataset Generation



\## Overview



To enable reliable dataset generation, netlists are serialized into a

JSON format instead of Python lists or in-memory objects.



This avoids unreadable list errors encountered during sampling and

allows downstream dataset scripts to consume netlists deterministically.



---



\## Where the JSON Is Generated



The JSON netlist is generated during the netlisting stage of pcell

evaluation.



Relevant files:

\- `src/glayout/util/netlist\_json.py`

\- pcell entry points (e.g. `lcm.py`)

\- higher-level composite / sampling scripts



The pcell itself does not write files directly. It returns a structured

netlist object which is then serialized to JSON by the dataset flow.



---



\## JSON Schema



Example JSON netlist:



```json

{

&nbsp; "cell": "lcm",

&nbsp; "devices": \[],

&nbsp; "nets": \[]

}



