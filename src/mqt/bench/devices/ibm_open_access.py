"""Module to manage open-access IBM devices."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from pathlib import Path

    from qiskit.providers.models import BackendProperties
    from qiskit.transpiler import Target

from mqt.bench.devices import Device, DeviceCalibration, Provider


class QubitProperties(TypedDict):
    """Class to store the properties of a single qubit."""

    T1: float  # us
    T2: float  # us
    eRO: float
    tRO: float  # ns
    eID: float
    eSX: float
    eX: float
    eECR: dict[str, float]
    tECR: dict[str, float]  # ns


class IBMOpenAccessCalibration(TypedDict):
    """Class to store the calibration data of an open-access IBM device."""

    name: str
    basis_gates: list[str]
    num_qubits: int
    connectivity: list[list[int]]
    properties: dict[str, QubitProperties]

class IBMOpenAccessProvider(Provider):
    """Class to manage open-access IBM devices."""

    provider_name = "ibm_open_access"

    @classmethod
    def get_available_device_names(cls) -> list[str]:
        """Get the names of all available open-access IBM devices."""
        return ["ibm_kyiv", "ibm_brisbane", "ibm_sherbrooke"]  # NOTE: update when adding new devices

    @classmethod
    def get_native_gates(cls) -> list[str]:
        """Get a list of provider specific native gates."""
        return ["id", "rz", "sx", "x", "ecr", "measure", "barrier"]  # ibm_kyiv, ibm_brisbane, ibm_sherbrooke

    @classmethod
    def import_backend(cls, path: Path) -> Device:
        """Import an open-access IBM backend.

        Arguments:
            path: the path to the JSON file containing the calibration data.

        Returns: the Device object
        """
        with path.open() as json_file:
            open_access_ibm_calibration = cast(IBMOpenAccessCalibration, json.load(json_file))

        device = Device()
        device.name = open_access_ibm_calibration["name"]
        device.num_qubits = open_access_ibm_calibration["num_qubits"]
        device.basis_gates = open_access_ibm_calibration["basis_gates"]
        device.coupling_map = list(open_access_ibm_calibration["connectivity"])

        calibration = DeviceCalibration()
        for qubit in range(device.num_qubits):
            calibration.single_qubit_gate_fidelity[qubit] = {
                "id": 1 - open_access_ibm_calibration["properties"][str(qubit)]["eID"],
                "rz": 1,  # rz is always perfect
                "sx": 1 - open_access_ibm_calibration["properties"][str(qubit)]["eSX"],
                "x": 1 - open_access_ibm_calibration["properties"][str(qubit)]["eX"]
            }
            calibration.readout_fidelity[qubit] = 1 - open_access_ibm_calibration["properties"][str(qubit)]["eRO"]
            # data in nanoseconds, convert to SI unit (seconds)
            calibration.readout_duration[qubit] = open_access_ibm_calibration["properties"][str(qubit)]["tRO"] * 1e-9
            # data in microseconds, convert to SI unit (seconds)
            calibration.t1[qubit] = open_access_ibm_calibration["properties"][str(qubit)]["T1"] * 1e-6
            calibration.t2[qubit] = open_access_ibm_calibration["properties"][str(qubit)]["T2"] * 1e-6

        for qubit1, qubit2 in device.coupling_map:
            edge = f"{qubit1}_{qubit2}"

            error = open_access_ibm_calibration["properties"][str(qubit1)]["eECR"][edge]
            calibration.two_qubit_gate_fidelity[(qubit1, qubit2)] = {"ecr": 1 - error}

            # data in nanoseconds, convert to SI unit (seconds)
            duration = open_access_ibm_calibration["properties"][str(qubit1)]["eECR"][edge] * 1e-9
            calibration.two_qubit_gate_duration[(qubit1, qubit2)] = {"ecr": duration}

        device.calibration = calibration
        return device

    @classmethod
    def __import_backend_properties(cls, backend_properties: BackendProperties) -> DeviceCalibration:
        """Import calibration data from a Qiskit `BackendProperties` object.

        Arguments:
            backend_properties: the Qiskit `BackendProperties` object.

        Returns: Collection of calibration data
        """
        calibration = DeviceCalibration()
        num_qubits = len(backend_properties.qubits)

        for qubit in range(num_qubits):
            calibration.t1[qubit] = cast(float, backend_properties.t1(qubit))
            calibration.t2[qubit] = cast(float, backend_properties.t2(qubit))
            calibration.readout_fidelity[qubit] = 1 - cast(float, backend_properties.readout_error(qubit))
            calibration.readout_duration[qubit] = cast(float, backend_properties.readout_length(qubit))

        calibration.single_qubit_gate_fidelity = {qubit: {} for qubit in range(num_qubits)}
        calibration.single_qubit_gate_duration = {qubit: {} for qubit in range(num_qubits)}
        for gate in backend_properties.gates:
            # Skip `reset` gate as its error information is not exposed.
            if gate.gate == "reset":
                continue

            error: float = backend_properties.gate_error(gate.gate, gate.qubits)
            duration: float = backend_properties.gate_length(gate.gate, gate.qubits)
            if len(gate.qubits) == 1:
                qubit = gate.qubits[0]
                calibration.single_qubit_gate_fidelity[qubit][gate.gate] = 1 - error
                calibration.single_qubit_gate_duration[qubit][gate.gate] = duration
            elif len(gate.qubits) == 2:
                qubit1, qubit2 = gate.qubits
                if (qubit1, qubit2) not in calibration.two_qubit_gate_fidelity:
                    calibration.two_qubit_gate_fidelity[(qubit1, qubit2)] = {}
                calibration.two_qubit_gate_fidelity[(qubit1, qubit2)][gate.gate] = 1 - error

                if (qubit1, qubit2) not in calibration.two_qubit_gate_duration:
                    calibration.two_qubit_gate_duration[(qubit1, qubit2)] = {}
                calibration.two_qubit_gate_duration[(qubit1, qubit2)][gate.gate] = duration

        return calibration

    @classmethod
    def __import_target(cls, target: Target) -> DeviceCalibration:
        """Import calibration data from a Qiskit `Target` object.

        Arguments:
            target: the Qiskit `Target` object.

        Returns: Collection of calibration data
        """
        calibration = DeviceCalibration()
        num_qubits = len(target.qubit_properties)

        for qubit in range(num_qubits):
            qubit_props = target.qubit_properties[qubit]
            calibration.t1[qubit] = cast(float, qubit_props.t1)
            calibration.t2[qubit] = cast(float, qubit_props.t2)

        calibration.single_qubit_gate_fidelity = {qubit: {} for qubit in range(num_qubits)}
        calibration.single_qubit_gate_duration = {qubit: {} for qubit in range(num_qubits)}
        coupling_map = target.build_coupling_map().get_edges()
        calibration.two_qubit_gate_fidelity = {(qubit1, qubit2): {} for qubit1, qubit2 in coupling_map}
        calibration.two_qubit_gate_duration = {(qubit1, qubit2): {} for qubit1, qubit2 in coupling_map}
        for instruction, qargs in target.instructions:
            # Skip `reset` and `delay` gate as their error information is not exposed.
            if instruction.name == "reset" or instruction.name == "delay":
                continue

            instruction_props = target[instruction.name][qargs]
            error: float = instruction_props.error
            duration: float = instruction_props.duration
            qubit = qargs[0]
            if instruction.name == "measure":
                calibration.readout_fidelity[qubit] = 1 - error
                calibration.readout_duration[qubit] = duration
            elif len(qargs) == 1:
                calibration.single_qubit_gate_fidelity[qubit][instruction.name] = 1 - error
                calibration.single_qubit_gate_duration[qubit][instruction.name] = duration
            elif len(qargs) == 2:
                qubit1, qubit2 = qargs
                calibration.two_qubit_gate_fidelity[(qubit1, qubit2)][instruction.name] = 1 - error
                calibration.two_qubit_gate_duration[(qubit1, qubit2)][instruction.name] = duration

        return calibration
