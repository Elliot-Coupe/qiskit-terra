# This code is part of Qiskit.
#
# (C) Copyright IBM 2020.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""ALAP Scheduling."""

import warnings

from qiskit.circuit import Delay, Qubit, Measure
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler.exceptions import TranspilerError
from qiskit.transpiler.passes.scheduling.time_unit_conversion import TimeUnitConversion

from .base_scheduler import BaseSchedulerTransform


class ALAPSchedule(BaseSchedulerTransform):
    """ALAP Scheduling pass, which schedules the **stop** time of instructions as late as possible.

    See :class:`~qiskit.transpiler.passes.scheduling.base_scheduler.BaseSchedulerTransform` for the
    detailed behavior of the control flow operation, i.e. ``c_if``.

    .. note::

        This base class has been superseded by :class:`~.ALAPScheduleAnalysis` and
        the new scheduling workflow. It will be deprecated and subsequently
        removed in a future release.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        warnings.warn(
            "The ALAPSchedule class has been supersceded by the ALAPScheduleAnalysis class "
            "which performs the as analysis pass that requires a padding pass to later modify "
            "the circuit. This class will be deprecated in a future release and subsequently "
            "removed after that.",
            PendingDeprecationWarning,
        )

    def run(self, dag):
        """Run the ALAPSchedule pass on `dag`.

        Args:
            dag (DAGCircuit): DAG to schedule.

        Returns:
            DAGCircuit: A scheduled DAG.

        Raises:
            TranspilerError: if the circuit is not mapped on physical qubits.
        """
        if len(dag.qregs) != 1 or dag.qregs.get("q", None) is None:
            raise TranspilerError("ALAP schedule runs on physical circuits only")

        time_unit = self.property_set["time_unit"]
        new_dag = DAGCircuit()
        for qreg in dag.qregs.values():
            new_dag.add_qreg(qreg)
        for creg in dag.cregs.values():
            new_dag.add_creg(creg)

        idle_before = {q: 0 for q in dag.qubits + dag.clbits}
        bit_indices = {bit: index for index, bit in enumerate(dag.qubits)}
        for node in reversed(list(dag.topological_op_nodes())):
            # validate node.op.duration
            if node.op.duration is None:
                indices = [bit_indices[qarg] for qarg in node.qargs]
                if dag.has_calibration_for(node):
                    node.op.duration = dag.calibrations[node.op.name][
                        (tuple(indices), tuple(float(p) for p in node.op.params))
                    ].duration

                if node.op.duration is None:
                    raise TranspilerError(
                        f"Duration of {node.op.name} on qubits {indices} is not found."
                    )
            if isinstance(node.op.duration, ParameterExpression):
                indices = [bit_indices[qarg] for qarg in node.qargs]
                raise TranspilerError(
                    f"Parameterized duration ({node.op.duration}) "
                    f"of {node.op.name} on qubits {indices} is not bounded."
                )
            # choose appropriate clbit available time depending on op
            clbit_time_available = (
                clbit_writeable if isinstance(node.op, Measure) else clbit_readable
            )
            # correction to change clbit start time to qubit start time
            delta = 0 if isinstance(node.op, Measure) else node.op.duration
            # must wait for op.condition_bits as well as node.cargs
            start_time = max(
                itertools.chain(
                    (qubit_time_available[q] for q in node.qargs),
                    (clbit_time_available[c] - delta for c in node.cargs + node.op.condition_bits),
                )
            )

            pad_with_delays(node.qargs, until=start_time, unit=time_unit)

            for bit in node.qargs:
                delta = t0 - idle_before[bit]
                if delta > 0:
                    new_dag.apply_operation_front(Delay(delta, time_unit), [bit], [])
                idle_before[bit] = t1

            new_dag.apply_operation_front(node.op, node.qargs, node.cargs)

        circuit_duration = max(idle_before.values())
        for bit, before in idle_before.items():
            delta = circuit_duration - before
            if not (delta > 0 and isinstance(bit, Qubit)):
                continue
            new_dag.apply_operation_front(Delay(delta, time_unit), [bit], [])

        new_dag.name = dag.name
        new_dag.metadata = dag.metadata
        new_dag.calibrations = dag.calibrations

        # set circuit duration and unit to indicate it is scheduled
        new_dag.duration = circuit_duration
        new_dag.unit = time_unit

        return new_dag
