from os.path import join, dirname
from typing import Union, Optional
from copy import deepcopy

import re

class Netlist:
	"""Represents a SPICE netlist/subcircuit."""

	circuit_name: str = ""
	"""Name of the subcircuit."""
	nodes: list[str] = []
	"""List of nodes in the subcircuit."""
	global_nodes: list[str] = []
	"""List of the global nodes in the subcircuit."""

	designs_dir: str = join(dirname(__file__), 'designs')
	"""Path to the src/designs/ directory."""

	source_netlist: str = ""
	"""The source SPICE subcircuit (template) for the subcircuit. [Mako](https://makotemplates.org) templating syntax is supported."""
	instance_format: str = "X{name} {nodes} {circuit_name}"
	"""The format for the SPICE instantiation. Uses the Python string formatting syntax. `self.parameters`, `nodes`, `name`, and `circuit_name` are available parameters."""
	spice_netlist: str = ""
	"""The generated SPICE netlist."""

	sub_netlists: list['Netlist']
	"""List of the sub-netlists."""
	netlist_connections: list[list[str]]
	"""2D matrix of interconnections of the sub-netlists.

	The row and column number in the matrix represent the indices of the connected sub-netlists. The value represents the name of the wire connecting the nodes.
	"""

	# Variable to determine how many wires were created
	wire_index: int = 0
	"""The index of the next interconnection wire.

	The wires for interconnecting sub-netlists are named `wire{wire_index}`. This index is incremented each time a sub-netlist connection is made.
	"""

	parameters: dict = {}
	"""Dictionary of the high-level parameters."""

	def __init__(self, source_netlist: str = '', nodes: list[str] = [], circuit_name: Union[str, None] = None, instance_format: Optional[str] = None, parameters: dict = {}, sub_netlists: list['Netlist'] = []):
		"""Initializes a Netlist object.

		Override to load sub-netlists and parameters on initialization.
		"""
		self.parameters = {**self.parameters, **parameters}

		self.sub_netlists = []
		self.netlist_connections = []
		self.source_netlist = source_netlist
		self.nodes = nodes

		if circuit_name != None:
			self.circuit_name = circuit_name
		else:
			self.circuit_name = self.extract_subckt_name(self.source_netlist)

		if instance_format != None:
			self.instance_format = instance_format

		self.add_netlists(sub_netlists)

	def extract_subckt_name(self, netlist: str) -> str:
		"""Extracts the subcircuit name from the source SPICE."""
		for line in netlist.split('\n'):
			if line.count('subckt') != 0:
				return line.split(' ')[1]

		return 'Netlist'

	def generate_instance(self, name: Optional[str] = None, nodes: Optional[list[str]] = None, instance_format: Optional[str] = None) -> str:
		"""Generates an instance of the netlist subcircuit.
		Override to insert parameters in the instance.
		"""
		if name == None:
			name = self.circuit_name

		if instance_format == None:
			instance_format = self.instance_format

		if nodes == None:
			nodes = self.nodes

		params = {
			**self.generate_source_netlist_params(),
			'nodes': ' '.join(nodes),
			'name': name
		}

		return instance_format.format(**params)

	def read_source_netlist(self, netlist_src: str) -> str:
		"""Reads a source SPICE subcircuit template from a SPICE file. [Mako](https://makotemplates.org) templating syntax is supported in the source SPICE netlist."""
		self.source_netlist = open(join(self.designs_dir, netlist_src)).read()
		return self.source_netlist

	def _explicit_nets(self) -> set[str]:
		"""Names of the nets that were named explicitly through `connect_node`."""
		if "_explicit_net_names" not in self.__dict__:
			self._explicit_net_names = set()
		return self._explicit_net_names

	def _connected_terminals(self) -> set[tuple[int, int]]:
		"""Terminals (sub-netlist index, node index) that took part in a connection call."""
		if "_connected_terminal_set" not in self.__dict__:
			self._connected_terminal_set = set()
		return self._connected_terminal_set

	def _label_members(self) -> dict[str, set[tuple[int, int]]]:
		"""Index of the connected terminals by net label. Only `_assign` and `_rollback` change it."""
		if "_label_member_index" not in self.__dict__:
			self._label_member_index = {}
		return self._label_member_index

	def _pin_wire_labels(self) -> set[str]:
		"""Default pin names that look like `wire{N}`, so that `_new_wire` never mints them. Sub-netlists are scanned once."""
		if "_pin_wire_label_set" not in self.__dict__:
			self._pin_wire_label_set = set()
			self._pin_scanned_netlists = 0
		for sub_netlist in self.sub_netlists[self._pin_scanned_netlists:]:
			self._pin_wire_label_set.update(node for node in sub_netlist.nodes if re.match(r"^wire\d+$", node))
		self._pin_scanned_netlists = len(self.sub_netlists)
		return self._pin_wire_label_set

	def _is_auto_wire(self, net: str) -> bool:
		"""Whether `net` is one of the `wire{N}` names minted by `connect_subnets`."""
		return re.match(r"^wire\d+$", net) is not None and net not in self._explicit_nets()

	def _net_members(self, net_index: int, node_index: int) -> set[tuple[int, int]]:
		"""All terminals that were connected to the given terminal (itself included).

		A terminal that never took part in a connection still carries its default label
		(its own pin name). That label can coincide with the name of another net by
		accident; it is not a connection, so such a terminal is a net of its own.

		The returned set of a connected terminal is the live index entry: do not modify it.
		"""
		terminal = (net_index, node_index)
		if terminal not in self._connected_terminals():
			return {terminal}
		return self._label_members()[self.netlist_connections[net_index][node_index]]

	def _new_wire(self) -> str:
		"""Mints a wire name that does not collide with any name already in use."""
		index = self._label_members()
		explicit = self._explicit_nets()
		pins = self._pin_wire_labels()
		while (f"wire{self.wire_index}" in index or f"wire{self.wire_index}" in explicit
			or f"wire{self.wire_index}" in pins):
			self.wire_index += 1
		wire = f"wire{self.wire_index}"
		self.wire_index += 1
		return wire

	def _assign(self, terminals, label: str, journal: list):
		"""Puts the terminals on the net `label` and records what is needed to undo it in `journal`."""
		connected = self._connected_terminals()
		index = self._label_members()
		for terminal in list(terminals):
			i, j = terminal
			old = self.netlist_connections[i][j]
			was_connected = terminal in connected
			journal.append(("t", terminal, old, was_connected))
			if was_connected:
				members = index[old]
				members.discard(terminal)
				if not members:
					del index[old]
			self.netlist_connections[i][j] = label
			index.setdefault(label, set()).add(terminal)
			connected.add(terminal)

	def _rollback(self, journal: list, wire_index: int):
		"""Undoes everything recorded in `journal`, so that a call that raised leaves the netlist as it found it."""
		connected = self._connected_terminals()
		index = self._label_members()
		for entry in reversed(journal):
			if entry[0] == "e":
				self._explicit_nets().discard(entry[1])
				continue
			_, terminal, old, was_connected = entry
			i, j = terminal
			members = index[self.netlist_connections[i][j]]
			members.discard(terminal)
			if not members:
				del index[self.netlist_connections[i][j]]
			self.netlist_connections[i][j] = old
			if was_connected:
				index.setdefault(old, set()).add(terminal)
			else:
				connected.discard(terminal)
		self.wire_index = wire_index

	def _connect_pair(self, net1_index: int, node1_index: int, net2_index: int, node2_index: int, journal: list):
		"""Joins two terminals (and, with them, their whole nets). See `connect_subnets`."""
		netlist1 = self.sub_netlists[net1_index]
		netlist2 = self.sub_netlists[net2_index]
		node1 = netlist1.nodes[node1_index]
		node2 = netlist2.nodes[node2_index]

		members1 = self._net_members(net1_index, node1_index)
		if (net2_index, node2_index) in members1:
			# already on the same net
			return
		members2 = self._net_members(net2_index, node2_index)

		# only a terminal that was connected before can be on a named net or a wire
		connected = self._connected_terminals()
		explicit = self._explicit_nets()
		terminal1_connected = (net1_index, node1_index) in connected
		terminal2_connected = (net2_index, node2_index) in connected
		label1 = self.netlist_connections[net1_index][node1_index]
		label2 = self.netlist_connections[net2_index][node2_index]
		named1 = terminal1_connected and label1 in explicit
		named2 = terminal2_connected and label2 in explicit
		wire1 = terminal1_connected and self._is_auto_wire(label1)
		wire2 = terminal2_connected and self._is_auto_wire(label2)

		if named1 and named2:
			raise ValueError(
				f"Cannot connect {netlist1.circuit_name}.{node1} (net '{label1}') to "
				f"{netlist2.circuit_name}.{node2} (net '{label2}'): they are different "
				f"named nets in '{self.circuit_name}' and would be shorted together."
			)

		# the merged net keeps an explicit name, else an existing wire, else a new wire
		if named1:
			connection_wire = label1
		elif named2:
			connection_wire = label2
		elif wire1:
			connection_wire = label1
		elif wire2:
			connection_wire = label2
		else:
			connection_wire = self._new_wire()

		# every member of both nets ends up on connection_wire; a net that already carries it is left alone
		relabel1 = not terminal1_connected or label1 != connection_wire
		relabel2 = not terminal2_connected or label2 != connection_wire
		if relabel1:
			self._assign(members1, connection_wire, journal)
		if relabel2:
			self._assign(members2, connection_wire, journal)

	def connect_subnets(
		self,
		net1: Union[int, 'Netlist'],
		net2: Union[int, 'Netlist'],
		node_mapping: list[tuple[str, str]]
	):
		"""Adds a connection between two sub-netlists.

		The connection is an equivalence: afterwards the two nodes, and every node that
		was already connected to either of them, are on a single net. If either side is
		already on a net named through `connect_node`, the merged net keeps that name.

		The call is all-or-nothing: if it raises, no pair of `node_mapping` has been applied.

		Parameters:
			- `net1`: The netlist to connect. Either a reference to the Netlist object or it's index in the `sub_netlists` list.
			- `net2`: The netlist to connect to. Either a reference to the Netlist object or it's index in the `sub_netlists` list.
			- `node_mapping`: A list of 2-element tuples representing the connections between nodes of the netlists. The first element in the tuple is the name of the node of `net1` and the second value is the name of the node in `net2` to connect to.

		Raises:
			- `ValueError`: if the connection would join two nets that were given different names through `connect_node` (for example a supply and a ground).
		"""
		journal = []
		wire_index = self.wire_index
		try:
			for mapping in node_mapping:
				node1, node2 = mapping

				net1_index = net1 if type(net1) == int else self.sub_netlists.index(net1)
				net2_index = net2 if type(net2) == int else self.sub_netlists.index(net2)

				node1_index = self.sub_netlists[net1_index].nodes.index(node1)
				node2_index = self.sub_netlists[net2_index].nodes.index(node2)

				self._connect_pair(net1_index, node1_index, net2_index, node2_index, journal)
		except Exception:
			self._rollback(journal, wire_index)
			raise

	def _connect_node_pair(self, net_index: int, net_node: str, top_level_node: str, journal: list):
		"""Moves a terminal, and the net it is on, onto a top-level node. See `connect_node`."""
		net = self.sub_netlists[net_index]
		node_index = net.nodes.index(net_node)

		current = self.netlist_connections[net_index][node_index]
		connected = self._connected_terminals()
		explicit = self._explicit_nets()
		terminal_connected = (net_index, node_index) in connected

		if terminal_connected and current in explicit and current != top_level_node:
			raise ValueError(
				f"Cannot connect {net.circuit_name}.{net_node} to '{top_level_node}': it is "
				f"already on the net '{current}' in '{self.circuit_name}'."
			)

		if self._is_auto_wire(top_level_node) and any(top_level_node in row for row in self.netlist_connections):
			raise ValueError(
				f"Cannot name a net '{top_level_node}' in '{self.circuit_name}': that name "
				f"is already used by an auto-generated wire."
			)

		members = self._net_members(net_index, node_index)
		if top_level_node not in explicit:
			explicit.add(top_level_node)
			journal.append(("e", top_level_node))
		if not terminal_connected or current != top_level_node:
			self._assign(members, top_level_node, journal)

	def connect_node(
		self,
		net: Union[int, 'Netlist'],
		node_mapping: list[tuple[str, str]]
	):
		"""Connects a sub-netlist to a top-level node.

		Every node that is already connected to the given node is moved onto the
		top-level node as well, regardless of the order of the calls.

		The call is all-or-nothing: if it raises, no pair of `node_mapping` has been applied.

		Parameters:
		- `net`: The sub-netlist to connect. Either a reference to the Netlist object or it's index in the `sub_netlists` list.
		- `node_mapping`: A list of 2-element tuples representing the connections between the netlist nodes and the top-level nodes. The first element in the tuple is the name of the node of `net` and the second value is the name of the top-level to connect to.

		Raises:
		- `ValueError`: if the node is already on a net with a different name (set through `connect_node`), or if the name is already used by an auto-generated `wire{N}` net.
		"""
		net_index = net if type(net) == int else self.sub_netlists.index(net)

		journal = []
		wire_index = self.wire_index
		try:
			for mapping in node_mapping:
				net_node, top_level_node = mapping
				self._connect_node_pair(net_index, net_node, top_level_node, journal)
		except Exception:
			self._rollback(journal, wire_index)
			raise

	def add_netlists(self, netlists: list['Netlist']):
		"""Adds sub-netlists.

		Parameters:
		- `netlists`: A list of Netlist objects to add.
		"""
		for netlist in netlists:
			self.sub_netlists.append(netlist)
			self.netlist_connections.append(netlist.nodes.copy())

	def connect_netlist(self, netlist: 'Netlist', node_mapping: list[tuple[str, str]]) -> int:
		"""Adds a sub-netlist and connects it to top-level nodes.

		Parameters:
		- `netlist`: The netlist object to add.
		- `node_mapping`: A list of 2-element tuples representing the connections between the netlist nodes and the top-level nodes. The first element in the tuple is the name of the node of `netlist` and the second value is the name of the top-level to connect to.

		If the connection raises, the netlist is not added.
		"""
		self.add_netlists([deepcopy(netlist)])
		netlist_index = len(self.sub_netlists) - 1

		try:
			self.connect_node(net=netlist_index, node_mapping=node_mapping)
		except Exception:
			# leave no half-added sub-netlist behind (connect_node has already undone its own changes)
			self.sub_netlists.pop()
			self.netlist_connections.pop()
			raise

		return netlist_index

	def generate_source_netlist_params(self, circuit_name: Optional[str] = None) -> dict:
		"""Generates the parameters to be inserted in the source SPICE netlist. Uses the Python template string format."""
		return {
			'circuit_name': circuit_name if circuit_name != None else self.circuit_name,
			'nodes': ' '.join(self.nodes),
			**self.parameters
		}

	def __generate_self_subcircuit(self, prefix: str = '', suffix: str = '', with_pins: bool = True) -> str:
		"""Generates the top-level SPICE subcircuit directive.
		The name of the subcircuit is set by `self.circuit_name`.
		"""
		generated_circuit_name = f"{prefix}{self.circuit_name}{suffix}"

		if self.source_netlist != "":
			return self.source_netlist.format(**self.generate_source_netlist_params(generated_circuit_name))

		elif len(self.sub_netlists) > 0:
			if with_pins:
				main_circuit = f".subckt {generated_circuit_name} {' '.join(self.nodes)}\n"
			else:
				main_circuit = f".subckt {generated_circuit_name}\n"
    
			for i, netlist in enumerate(self.sub_netlists):
				main_circuit += netlist.generate_instance(str(i), self.netlist_connections[i]) + "\n"

			main_circuit += f".ends {generated_circuit_name}"

			return main_circuit

		else:
			return ""

	def get_subcircuits_netlist_map(self, sub_netlists_only = False) -> dict[str, list['Netlist']]:
		"""Generates a list of all the unique SPICE subcircuits directives used in the netlist."""
		subcircuits = dict()

		# Get sub netlists' subcircuits
		for netlist in self.sub_netlists:
			subnetlist_subcircuits = netlist.get_subcircuits_netlist_map()

			# For each subnetlists' subcircuit
			for subckt in subnetlist_subcircuits:
				subckt_netlists = subnetlist_subcircuits[subckt]

				if subckt not in subcircuits:
					# If it is unique, create an entry in the dict
					subcircuits[subckt] = [*subckt_netlists]
				else:
					# If it is not unique, append the netlists to the dict
					subcircuits[subckt] += subckt_netlists


		if not sub_netlists_only:
			self_subckt = self.__generate_self_subcircuit()
			if self_subckt not in subcircuits:
				subcircuits[self_subckt] = [self]

		return subcircuits

	def get_global_nodes_list(self) -> set[str]:
		"""Generates a list of unique global nodes used in the netlist."""
		global_nodes = set()

		for netlist in self.sub_netlists:
			global_nodes.update(netlist.global_nodes)

		global_nodes.update(set(self.global_nodes))

		return global_nodes

	def generate_netlist(self, only_subcircuits: bool = False, with_pins: bool = True) -> str:
		"""Generates the final SPICE netlist for the design.

		The final netlist is a set of SPICE subcircuit directives and global directives. The top-level subcircuit is set by `self.circuit_name`.

		Parameters:
		- `only_subcircuits`: Only generates the subcircuit directives if set to `True`. (Default: `False`)
		"""

		# GENERATE UNIQUE SUBCIRCUIT DiRECTIVES
		subcircuits_netlist_map = self.get_subcircuits_netlist_map(sub_netlists_only=True)

		subcircuit_suffixes = dict()
		# Get the unique netlists' list and set their suffixes
		for subckt in subcircuits_netlist_map:
			netlists = subcircuits_netlist_map[subckt]
			# All of these subcircuits will have the same name, so use any one
			subckt_name = netlists[0].circuit_name

			if subckt_name in subcircuit_suffixes:
				# If a suffix exists, use it and increment it
				for netlist in netlists: netlist.circuit_name = f"{netlist.circuit_name}_{subcircuit_suffixes[subckt_name]}"
				subcircuit_suffixes[subckt_name] += 1
			else:
				# If a suffix doesn't exist, create it.
				subcircuit_suffixes[subckt_name] = 1

		unique_subcircuits_list = []
		# Generate all the unique subcircuits (generation is done again since suffixes were updated)
		for subckt in subcircuits_netlist_map:
			unique_subcircuits_list.append(
				# Use any one since all will be equal
				subcircuits_netlist_map[subckt][0].__generate_self_subcircuit()
			)
		# /GENERATE UNIQUE SUBCIRCUIT DiRECTIVES

		# GENERATE THE FINAL NETLIST
		subcircuits = '\n\n'.join(unique_subcircuits_list)
		main_circuit = self.__generate_self_subcircuit(with_pins=with_pins)
		global_nodes = ' '.join(self.get_global_nodes_list())

		self.spice_netlist = "" 

		if len(global_nodes) > 0 and not only_subcircuits: self.spice_netlist += f".global {global_nodes}\n\n"

		self.spice_netlist += subcircuits + "\n\n"
		self.spice_netlist += main_circuit
		# /GENERATE THE FINAL NETLIST

		return self.spice_netlist
