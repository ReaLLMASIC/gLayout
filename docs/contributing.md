Contributor Guidelines - How to use GLayout


Open a Pull Request with title Draft:CP25:<Team Name>:Design Name
Copy the path of the new fork created by the previous step
https://github.com/Subhampal9/analog_vibes_chipathon_2024.git
Use “mkdir” to make a new directory, name it “Chipathon25” (or any name of your choice).
Use “cd”  and move to the “Chipathon25” directory.
Clone the repo above with the command `git clone https://github.com/Subhampal9/analog_vibes_chipathon_2024.git`
Cd to OpenFasoc/…/.. / flow/
New Directoty with your design name
This Should have `..init.py..`
All *.py files` required for your design
        











Setting up VS Code
VS Code is recommended as it makes it easy using jupyter notebooks and terminals. Install it by doing a simple google search. Open VS code and if it asks you to install WSL, install it. Then you can use the terminal in VS code for all the further commands.

Setting up Git
Check if you have git installed
Use command “which git”, you should see a path where git is installed
If not, please install git from a simple google search
Use “mkdir” to make a new directory, name it “Chipathon25” (or any name of your choice).
Use “cd”  and move to the “Chipathon25” directory.
Navigate to Chipathon 2025 github page and find Code -> Copy button


Paste the copied URL after the command “git clone”. It will download the files and also help in push your request once you are ready to contribute.


Pull Request Guidelines
If the code being contributed follows the format mentioned above, only then is it eligible for review in a PR, so ensure that you match the format.

Write a brief description of the component in the PR’s description
Mention the components used in the cell
Attach DRC and LVS results if possible
As for commits, keep the following pointers in mind:
Signed commits are important to verify that they are by the person claiming to have made them (use git commit -S -m ‘commit message’)
Include a commit message for each commit
Do not split a single action item across commits unless the action item is significantly drawn out
Keep the PR as a draft until sure that it is ready for review
The component must be DRC and LVS clean (The will explained)
If any bugs are found, ensure that they are reported before you try to find a workaround
Take reference from the larger pcells implemented to get a rough idea of how pcells should ideally be coded up.
Running GLayout
Glayout is a Python-based code-to-layout framework that uses the GDSFactory in the backend to reduce the need to do manual analog layouts. Additionally, Glayout is a tool that generates DRC clean circuit layouts for any technology implementing the Glayout framework.


Glayout is composed of 2 main parts: the generic pdk framework and the circuit generators.  

The generic pdk framework allows for describing any pdk in a standardized format. The “pdk” sub-package within Glayout contains all code for the generic pdk class (known as “MappedPDK”) in addition to sky130 and gf180 MappedPDK objects. Because MappedPDK is a python class, describing a technology with a MappedPDK allows for passing the pdk as a python object.  The PDK generic circuit generator programs (also known as cells or components) are python functions which take as arguments a MappedPDK object and a set of optional layout parameters to produce a DRC clean layout.

Important GDSFactory Notes and GLayout Utilities
The GDSFactory API is highly versatile, and there are many useful features. It takes some experience to learn about all features and identify the most useful tools from GDSFactory. GDSFactory serves as the backend GDS manipulation library and as an object-oriented tool kit with several useful classes including: Components, Component References, and Ports. There are also common shapes such as components in GDSFactory, such as rectangles, circles, rectangular_rings, etc. To automate common tasks that do not fit into GDSFactory, Glayout includes many utility functions.

Component Functions
Components are the GDSFactory implementation of GDS cells. Components contain references to other components (Component Reference). Important methods are included below.
Component.name: get or set the name of a Component
Component.flatten(): flattens all references in the components
Component.remove_layers(): removes some layers from the component and return the modified component
Component.extract(): extract some layers from a component and return the modified component
Component.ports: dictionary of ports in the component
Component.add_ports(): add ports to the component
Component.add_padding(): add a layer surrounding the component
Component booleans: see the gdsfactory documentation for how to run boolean operations of components.
Component.write_gds(): write the gds to disk
Component.bbox: return bounding box of the component (xmin,ymin),(xmax,ymax). Glayout has an evaluate_bbox function which return the x and y dimensions of the bbox
insertion operator: ref = Component << Component_to_add
Component.add(): add an one of several types to a Component. (more flexible than << operator)
Component.ref()/.ref_center(): return a reference to a component

It is not possible to move Components in GDSFactory. GDSFactory has a Component cache, so moving a component may invalidate the cache, but there are situations where you want to move a component; For these situations, use the glayout move, movex and movey functions.


Component references are pointers to components. They have many of the same methods as Components with some additions.
ComponentReference.parent: the Component which this component reference points to
ComponentReference.movex, movey, move: you can move ComponentReferences
ComponentReference.get_ports_list(): get a list of ports in the component.

To add a ComponentReference to a Component, you cannot use the insertion operator. Use the Component.add() method.


A port describes a single edge of a polygon. The most useful port attributes are width, center tuple(x,y), orientation (degrees), and layer of the edge.
For example, the rectangle cell factory provided in gdsfactory.components.rectangle returns a Component type with the following port names: e1, e2, e3, e4.
e1=West, e2=North, e3=East, e4=South. The default naming scheme of ports in GDSFactory is not descriptive
use rename_ports_by_orientation, rename_ports_by_list functions and see below for port naming best practices guide
get_orientation: returns the letter (N,E,S,W) or degrees of orientation of the port.  by default it returns the one you do not have.
assert_port_manhattan: assert that a port or list or ports have orientation N, E, S, or W
assert_ports_perpindicular: assert two ports are perpendicular
set_port_orientation: return new port which is copy of old port but with new orientation
set_port_width: return a new port which is a copy of the old one, but with new width

A very important utility is align_comp_to_port: pass a component or componentReference and a port, and align the component to any edge of the port.

Port Naming Best Practices Guide
Complicated hierarchies can result in thousands of ports, so organizing ports is a necessity. The below best practices guide should be used to organize ports

Ports use the "_" syntax. Think of this like a directory tree for files. Each time you introduce a new level of hierarchy, you should add a prefix + "_" describing the cell.
For example, adding a via_array to the edge of a tapring, you should call tapring.add_ports(via_array.get_ports_list(),prefix="topviaarray")
The port rename functions look for the "_" syntax. You cannot use the port rename functions without this syntax.
The last 2 characters of a port name should be an "_" followed by the orientation (N, E, S, or W)
You can easily achieve this by calling rename_ports_by_orientation before returning a component (just the names end with "_" before calling this function)
USE PORTS: be sure to correctly add and label ports to components you make
Pcells (implemented and otherwise)
The currently implemented parametric cells, and planned cells can be found in this sheet. Contributors are encouraged to create the currently unimplemented pcells and open PRs! Detailed information on the implemented pcells has been omitted as it can be easily looked up while instantiating pcells using the docstrings.

Creating Components
Make a fork of the repo and install tools
Create a folder for your component in glayout/flow/blocks/
Name your folder after your component
Place the folder as a subfolder of the blocks folder
The following files are mandatory
 .py file is required for layout generation
 a .spice schematic file (netlist) used as reference
 a testbench for simulation 
Add the netlist to the component using the following command
with open(spice_netlist_file, 'r') as f:

        net = f.read()

        component.info['netlist'] = net

component should be DRC, LVS clean
If spice simulation applies, then a regression test is necessary         

Create an __init__.py
Add your file’s path to an __init__.py in your component directory’s top level.
This is required so that your component can be imported
Example: from glayout.flow.component.blocks.folder_name import component_name


Add a README with circuit parameters and other details
You can include a compressed jpeg image of the .gds layout

DRC and LVS checks for new components
DRC (magic and klayout) and LVS (netgen) is supported for glayout components

Magic DRC
drc_result = {pdk}.drc_magic(
   component,
   design_name
)

Here, {pdk} is the process-design-kit using which the component has been generated (sky130 and gf180 supported)
design_name is the component's specified name
if not already specified, do component.name = {some_design_name}
the pdk_root can also be specified (the function assumes /usr/bin/miniconda3/)
The magic drc report will be written to glayout/flow/regression/drc, unless an alternate path is specified (WIP, report is currently written out only if a path is specified)

Klayout DRC
klayout_drc_result = {pdk}.drc(
   component,
   report_path
)


This will run klayout drc on the component given (can also be a .gds file)
if the report path is given, the generated report will be written there
klayout_drc_result is a bool which says if drc is clean or not

Netgen LVS
netgen_lvs_result = {pdk}.lvs_netgen(
   component,
   design_name,
   report_path
)


This will run netgen lvs for the component, the design name must also be supplied
The cdl or spice netlist file can also be passed by overriding the cdl_path variable with the path to your desired input spice file
Details on how the extraction is done and the script itself can be found in the docstrings
The pdk_root, lvs setup file, the schematic reference spice file, and the magic drc file can all be passed as overrides
netgen_lvs_result is a dictionary that will continue the netgen and magic subprocess return codes and the result as a string
the lvs report will be written to glayout/flow/regression/lvs, unless an alternate path is specified (WIP, report is currently written out only if a path is specified)

Parametric Simulations (Work In Progress)
If the spice testbench for parametric simulations is also supplied, the following command can be run
                sim_code = run_simulations(spice_testbench, log_file, **kwargs)

This will spawn a subprocess that runs ngspice simulations using the spice_testbench file provided and directs logs to the log_file 

More information on the functions can be found in the docstrings in the `MappedPDK` class in `glayout/flow/pdk/mappedpdk/`

 CI Checks
The GitHub Actions CI workflow checks the following components for DRC (magic) and LVS
two stage opamp (miller compensated, common source pfet load)
differential pair (uses a common centroid placement)
pfet (configurable length, width, parallel devices)
nfet (same as above)
current mirror (uses a two transistor interdigitized placement)
Should you choose to contribute to the glayout/flow/components/, ensure that they are DRC and LVS clean, using the checks described in the section above
(WIP) Spice testbench simulations will be added for the opamp
Description of the GitHub Actions workflow -

A workflow, when run, will pull the latest stable image from Dockerhub
A container is run on top of this image, using similar commands to those in the OpenFASOC/Glayout Installation Guide
Based on the functionality being tested (for example: a pcell), a python script containing the necessary checks is run
If the return code of the python script is non zero, the workflow is deemed to have failed and the GitHub actions reflects this
If multiple things need to be checked, the scripts can be broken down into multiple sequential jobs, all of which have to pass for a CI check to be successful



Below is the flow for how contributor-added components will be evaluated by the Github Actions Workflow. The following are absolute musts to take care of when contributing code (in decreasing order of importance):

Default values must be provided for the component’s parameters. This is done as follows:
def my_cell(
   # say the cell is a current mirror
   ref_fet_width: Optional[float] = 5,
   mirror_fet_width: Optional[float] = 10,
   num_fingers: Options[int] = 2,
   tie_layers: Optional[tuple[Optional[str], Optional[str]]] = ("met1", "met2")
   # and so on
): -> Component # returns a gdsfactory.component type


Look at existing pcell examples to see how to code in an optimal manner
Include descriptive docstrings in the functions to describe what the cell is supposed to do. Using the vscode extension is helpful for templating the docstring

Best Practices
README
Write a README for your component.
Include the following:
a description of all cell parameters
detailed information about the circuit.
Describe also the layout (there could be one design with several layouts)
Netlist
Provide a raw SPICE netlist compatible with NGSpice.
Include the netlist in component.info["netlist"].
Run LVS on the component
generate component .gds using the code snippet below
run LVS as shown in the DRC and LVS checking section
Parametric sim Testbench
It is useful to include simulation testbenches where circuit performance can be tested with the latest tool versions.
This ensures the validity of design parameters after rigorous DRC and LVS checking
Add a spice simulation testbench for your designs and optionally a golden set of parameters to test the circuit against