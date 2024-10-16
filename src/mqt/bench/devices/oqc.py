"""Module to manage OQC devices."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from pathlib import Path

from .calibration import DeviceCalibration
from .device import Device
from .provider import Provider

if TYPE_CHECKING or sys.version_info >= (3, 10, 0):
    from importlib import resources
else:
    import importlib_resources as resources



class QubitProperties(TypedDict):
    """Class to store the properties of a single qubit."""

    T1: float
    T2: float
    fRB: float
    fRO: float
    qubit: float


class Coupling(TypedDict):
    """Class to store the connectivity of a two-qubit gate."""

    control_qubit: float
    target_qubit: float


class TwoQubitProperties(TypedDict):
    """Class to store the properties of a two-qubit gate."""

    coupling: Coupling
    fECR: float


class Properties(TypedDict):
    """Class to store the properties of a device."""

    one_qubit: dict[str, QubitProperties]
    two_qubit: dict[str, TwoQubitProperties]


class OQCCalibration(TypedDict):
    """Class to store the calibration data of an OQC device."""

    name: str
    basis_gates: list[str]
    num_qubits: int
    connectivity: list[list[int]]
    properties: Properties


class OQCProvider(Provider):
    """Class to manage OQC devices."""

    provider_name = "oqc"

    @classmethod
    def get_available_device_names(cls) -> list[str]:
        """Get the names of all available OQC devices."""
        return ["oqc_lucy"]  # NOTE: update when adding new devices

    @classmethod
    def get_native_gates(cls) -> list[str]:
        """Get a list of provider specific native gates."""
        return ["rz", "sx", "x", "ecr", "measure", "barrier"]  # lucy

    @classmethod
    def import_backend(cls, name: str) -> Device:
        """Import an OQC backend.

        Arguments
            name (str): The name of the OQC backend whose calibration data needs to be imported.
                            This name will be used to locate the corresponding JSON calibration file.

        Returns:
            Device: An instance of `Device`, loaded with the calibration data from the JSON file.
        """
        ref = resources.files("mqt.bench") / "calibration_files" / f"{name}_calibration.json"

        # Use 'as_file' to access the resource as a path
        with resources.as_file(ref) as json_path:
            # Open the file using json_path
            with json_path.open() as json_file:
                # Load the JSON data and cast it to IBMCalibration
                oqc_calibration = cast(OQCCalibration, json.load(json_file))

        device = Device()
        device.name = oqc_calibration["name"]
        device.num_qubits = oqc_calibration["num_qubits"]
        device.basis_gates = oqc_calibration["basis_gates"]
        device.coupling_map = list(oqc_calibration["connectivity"])

        calibration = DeviceCalibration()
        for qubit in range(device.num_qubits):
            calibration.single_qubit_gate_fidelity[qubit] = {
                gate: oqc_calibration["properties"]["one_qubit"][str(qubit)]["fRB"] for gate in ["rz", "sx", "x"]
            }
            calibration.readout_fidelity[qubit] = oqc_calibration["properties"]["one_qubit"][str(qubit)]["fRO"]
            # data in microseconds, convert to SI unit (seconds)
            calibration.t1[qubit] = oqc_calibration["properties"]["one_qubit"][str(qubit)]["T1"] * 1e-6
            calibration.t2[qubit] = oqc_calibration["properties"]["one_qubit"][str(qubit)]["T2"] * 1e-6

        for qubit1, qubit2 in device.coupling_map:
            calibration.two_qubit_gate_fidelity[qubit1, qubit2] = dict.fromkeys(
                ["ecr"], oqc_calibration["properties"]["two_qubit"][f"{qubit1}-{qubit2}"]["fECR"]
            )
        device.calibration = calibration
        return device
