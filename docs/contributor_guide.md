
# Contributor Guide: How to Use GLayout for Chipathon
This section guides you through the steps to contribute a new design to the GLayout project, especially in the context of Chipathon 2025 or similar events.

## Setting up VS Code 💻
VS Code is recommended because it makes working with Jupyter notebooks and terminals easier.
- Install VS Code (you can simply search “Download VS Code” on Google)
- Open VS Code — if prompted to install WSL (Windows Subsystem for Linux), allow the installation
- Once installed, you can use the built-in terminal for all future commands

## Setting Up Git 💼
- Check if Git is installed 
  - Use the following command in your terminal and you should see a path where git is installed
    ```shell
    which git
    ```
  - If not, please install Git from a simple google search

- Use “mkdir” to make a new directory, name it “Chipathon25” (or any name of your choice).
- Use “cd”  and move to the “Chipathon25” directory.
  ```shell
  mkdir Chipathon25 # or any directory name of your choice
  cd Chipathon25
  ```
- Navigate to [Chipathon 2025 github page](https://github.com/sscs-ose/sscs-ose-chipathon.github.io) and find Code -> Copy button
  <img src="./_images/chipathon_2025_github.png" width="1500" height="400">
  </p>
- Paste the copied URL after the command “git clone”. It will download the files and also help in push your request once you are ready to contribute.
  <p align="center">
  <img src="./_images/git-clone.png" width="700" height="100">
  </p>

## Pull Request Guidelines 📬 
Only contributions that follow the required format will be eligible for review. Please ensure the following:

1. Write a brief description of the component in the PR’s description
2. Mention the components used in the cell
3. Attach **DRC and LVS results** if possible 
4.  for commits, keep the following pointers in mind:
    - Use signed commits to verify authorship
    - Include a commit message for each commit
    - Do not split a single action item across commits unless the action item is significantly drawn out
      ```bash 
        git commit -S -m "commit message"
      ```
5. Keep the PR as a draft until sure that it is ready for review
6. The component must be DRC and LVS clean (The will explained)
7. If any bugs are found, ensure that they are reported before you try to find a workaround
8. Take reference from the larger pcells implemented to get a rough idea of how pcells should ideally be coded up. 

## Running GLayout 🛠️

**GLayout** is a Python-based code-to-layout framework that leverages `gdsfactory` as its backend to automate analog layout design. 

Additionally, Glayout is a tool that generates DRC clean circuit layouts for any technology implementing the Glayout framework.

Glayout is composed of 2 main parts:
- Generic pdk framework
- Circuit generators.

The generic pdk framework allows for describing any pdk in a standardized format. The `pdk` sub-package within Glayout contains all code for the generic pdk class (known as `MappedPDK`) in addition to sky130 and gf180 MappedPDK objects. Because MappedPDK is a python class, describing a technology with a MappedPDK allows for passing the pdk as a python object. The PDK generic circuit generator programs (also known as cells or components) are python functions which take as arguments a MappedPDK object and a set of optional layout parameters to produce a DRC clean layout.

## Important GDSFactory Notes and GLayout Utilities

The GDSFactory API is highly versatile, and there are many useful features. It takes some experience to learn about all features and identify the most useful tools from GDSFactory. GDSFactory serves as the backend GDS manipulation library and as an object-oriented tool kit with several useful classes including: Components, Component References, and Ports. There are also common shapes such as components in GDSFactory, such as rectangles, circles, rectangular_rings, etc. To automate common tasks that do not fit into GDSFactory, Glayout includes many utility functions.

### Component Functions

Components are the GDSFactory implementation of GDS cells. Components contain references to other components (Component Reference). Important methods:

- `Component.name`: get or set the name of a Component
- `Component.flatten()`: flattens all references in the components
- `Component.remove_layers()`: removes some layers from the component and return the modified component
- `Component.extract()`: extract some layers from a component and return the modified component
- `Component.ports`: dictionary of ports in the component
- `Component.add_ports()`: add ports to the component
- `Component.add_padding()`: add a layer surrounding the component
- Boolean operations: see the GDSFactory docs
- `Component.write_gds()`: write the gds to disk
- `Component.bbox`: return bounding box of the component (xmin,ymin),(xmax,ymax).
- `evaluate_bbox`: return the x and y dimensions of the bbox
- Insertion: `ref = Component << Component_to_add`
- `Component.add()`: add an one of several types to a Component. (more flexible than << operator)
- `Component.ref()`, `.ref_center()`: return a reference to a component

### Component References
It is not possible to move Components in GDSFactory. GDSFactory has a Component cache, so moving a component may invalidate the cache, but there are situations where you want to move a component; For these situations, use the glayout move, movex and movey functions.
- Component references are pointers to components. They have many of the same methods as Components with some additions
- `ComponentReference.parent`: Component which this reference points to
- `ComponentReference.movex`, `ComponentReference.movey`, `ComponentReference.move`: you can move ComponentReferences
- `ComponentReference.get_ports_list()`:get a list of ports in the component.
- `Component.add()` to add a `ComponentReference` to a Component

### Ports
A port describes a single edge of a polygon. The most useful port attributes are **width**, **center tuple(x,y)**, **orientation (degrees)** ,and **layer of the edge**.
- For example, the rectangle cell factory provided in `gdsfactory.components.rectangle`, which returns a Component type with the following port names:
 e1, e2, e3, e4.

- e1 = West, e2 = North, e3 = East, e4 = South. The default naming scheme of ports in GDSFactory is not descriptive

- Use `rename_ports_by_orientation`, `rename_ports_by_list`functions and see below for port naming best practices guide
- `get_orientation`: returns the letter (N,E,S,W) or degrees of orientation of the port.by default it returns the one you do not have
- `assert_port_manhattan`: assert that a port or list or ports have orientation N, E, S, or W
- `assert_ports_perpendicular`: assert two ports are perpendicular
- `set_port_orientation`: return new port which is copy of old port but with new orientation
- `set_port_width`: return a new port which is a copy of the old one, but with new width
- `align_comp_to_port()`: pass a component or componentReference and a port, and align the component to any edge of the port.


### Port Naming Best Practices

- Use `_` in names for hierarchy. Think of this like a directory tree for files. Each time you introduce a new level of  hierarchy, you should add a prefix + "_" describing the cell. Example (Adding a via_array to the edge of a tapring):
  ```shell
  tapring.add_ports(via_array.get_ports_list(),prefix="topviaarray")
  ```
- The last 2 characters of a port name must end in `_N`, `_E`, `_S`, `_W`; Simply achieve this by calling `rename_ports_by_orientation` before returning
- **USE PORTS**: be sure to correctly add and label ports to components you make

## Pcells (Implemented and Otherwise)
The currently implemented parametric cells, and planned cells can be found in this [sheet](https://docs.google.com/spreadsheets/d/1KGBN63gHc-hpxVrqoAoOkerA7bl1-sZ44X4uEn-ILGE/edit?gid=0#gid=0).
Contributors are encouraged to implement unimplemented Pcells. Refer to docstrings for implemented ones.

## Creating Components

1. Make a fork of the repo and install tools
2. Create a folder for your component in `glayout/flow/blocks/`
    - Name your folder after your component
    - Place the folder as a subfolder of the `blocks` folder
    - The following files are mandatory
      - `.py` file is required for layout generation
      - a .spice schematic file (netlist) used as reference
      - a testbench for simulation 
    - Add the netlist to the component using the following command
      ```shell
      with open(spice_netlist_file, 'r') as f:
        net = f.read()
        component.info['netlist'] = net
      ```
      - Component should be DRC, LVS clean
      - If spice simulation applies, then a regression test is necessary 
3. Create an `__init__.py`
    - Add your file’s path to an `__init__.py` in your component directory’s top level.
    - This is required so that your component can be imported
    - Example: `from glayout.flow.component.blocks.folder_name import component_name`
4. Add a README with circuit parameters and other details
    - You can include a compressed jpeg image of the `.gds` layout

## DRC and LVS Checks
DRC (magic and klayout) and LVS (netgen) is supported for glayout components

### Magic DRC
  ```shell
  drc_result = {pdk}.drc_magic(
    component, 
    design_name
    )
  ```
  - Here, `{pdk}` is the process-design-kit using which the component has been generated (sky130 and gf180 supported)
  - `design_name` is the component's specified name
    - if not already specified, do `component.name = {some_design_name}`
  - the pdk_root can also be specified (the function assumes `/usr/bin/miniconda3/`)
  - The magic drc report will be written to `glayout/flow/regression/drc`, unless an alternate path is specified (**WIP**, report is currently written out only if a path is specified)


### Klayout DRC
```shell
klayout_drc_result = {pdk}.drc(
  component, 
  report_path
  )
```
  - This will run klayout drc on the component given (can also be a `.gds` file)
  - if the report path is given, the generated report will be written there
  - `klayout_drc_result` is a bool which says if drc is clean or not

### Netgen LVS
```python
netgen_lvs_result = {pdk}.lvs_netgen(
  component, 
  design_name, 
  report_path
  )
```
  - This will run netgen lvs for the component, the design name must also be supplied
  - The cdl or spice netlist file can also be passed by overriding the `cdl_path` variable with the path to your desired input spice file
  - Details on how the extraction is done and the script itself can be found in the docstrings
  - The pdk_root, lvs setup file, the schematic reference spice file, and the magic drc file can all be passed as overrides
  - `netgen_lvs_result` is a dictionary that will continue the netgen and magic subprocess return codes and the result as a string
  - The lvs report will be written to `glayout/flow/regression/lvs`, unless an alternate path is specified (WIP, report is currently written out only if a path is specified)


## Parametric Simulations (Work In Progress)
- If the spice testbench for parametric simulations is also supplied, the following command can be run
  ```shell
  sim_code = run_simulations(spice_testbench, log_file, **kwargs)
  ```
- This will spawn a subprocess that runs ngspice simulations using the spice_testbench file provided and directs logs to the log_file 

> More information on the functions can be found in the docstrings in the `MappedPDK` class in `glayout/flow/pdk/mappedpdk/`

## CI Checks
1. The GitHub Actions CI workflow checks the following components for DRC (magic) and LVS
   - ***Two stage opamp*** (miller compensated, common source pfet load)
    - ***Differential pair*** (uses a common centroid placement)
    - ***pfet*** (configurable length, width, parallel devices)
    - ***nfet*** (same as above)
    - ***Current mirror*** (uses a two transistor interdigitized placement)

2. Contributors are still encouraged to:
    - Contribute to `glayout/flow/components/`
    - Ensure they are DRC and LVS clean, ,using the checks described in the section above
3. (**WIP**) Spice testbench simulations will be added for the opamp

### GitHub Actions Workflow
- A workflow, when run, will pull the latest stable image from Dockerhub
- A container is run on top of this image, using similar commands to those in the OpenFASOC/Glayout Installation Guide 
- Based on the functionality being tested (for example: a pcell), a python script containing the necessary checks is run
- If the return code of the python script is non zero, the workflow is deemed to have failed and the GitHub actions reflects this
- If multiple things need to be checked, the scripts can be broken down into multiple sequential jobs, all of which have to pass for a CI check to be successful 

![General_CI_Flow](_images/general_ci_flow.png)

Below is the flow for how contributor-added components will be evaluated by the Github Actions Workflow. The following are absolute musts to take care of when contributing code (in decreasing order of importance): 

1. 1.Default values must be provided for the component’s parameters. This is done as follows:
    ```python
    def my_cell(
        ref_fet_width: Optional[float] = 5,
        mirror_fet_width: Optional[float] = 10,
        num_fingers: Optional[int] = 2,
        tie_layers: Optional[tuple[Optional[str], Optional[str]]] = ("met1", "met2")
    ): -> Component
    ```
2. Look at existing pcell examples to see how to code in an optimal manner
3. Include descriptive docstrings in the functions to describe what the cell is supposed to do. Using the [vscode extension](https://marketplace.visualstudio.com/items?itemName=njpwerner.autodocstring) is helpful for templating the docstring
<p align="center">
<img src="./_images/action_workflow.png" width="500" height="850">
</p>

## Best Practices for Contributing Components
### README
Every component should have a `README.md` file with:
- A Description of All Cell Parameters  
- Detailed Information about the Circuit.  
- A Description of Layout (there could be one design with several layouts)

### Netlist

1. Provide a raw SPICE netlist compatible with NGSpice.
2. Include the netlist in`component.info["netlist"]`
3. Run LVS on the component
4. Generate component `.gds` using the code snippet below
5. Run LVS as shown in the DRC and LVS checking section

### Parametric sim Testbench

1. It is useful to include simulation testbenches where circuit performance can be tested with the latest tool versions. 
2. This ensures the validity of design parameters after rigorous DRC and LVS checking 
3. Add a *spice simulation testbench* for your designs and optionally a golden set of parameters to test the circuit against
