# This code is part of Qiskit.
#
# (C) Copyright IBM 2017, 2018.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Manager for a set of Passes and their scheduling during transpilation."""

import io
import re
from typing import Union, List, Callable, Dict, Any

import dill

from qiskit.visualization import pass_manager_drawer
from qiskit.tools.parallel import parallel_map
from qiskit.circuit import QuantumCircuit
from .basepasses import BasePass
from .exceptions import TranspilerError
from .runningpassmanager import RunningPassManager, FlowController


class PassManager:
    """Manager for a set of Passes and their scheduling during transpilation."""

    def __init__(self, passes: Union[BasePass, List[BasePass]] = None, max_iteration: int = 1000):
        """Initialize an empty `PassManager` object (with no passes scheduled).

        Args:
            passes: A pass set (as defined in :py:func:`qiskit.transpiler.PassManager.append`)
                to be added to the pass manager schedule.
            max_iteration: The maximum number of iterations the schedule will be looped if the
                condition is not met.
        """
        # the pass manager's schedule of passes, including any control-flow.
        # Populated via PassManager.append().

        self._pass_sets = []
        if passes is not None:
            self.append(passes)
        self.max_iteration = max_iteration
        self.property_set = None

    def append(
        self,
        passes: Union[BasePass, List[BasePass]],
        max_iteration: int = None,
        **flow_controller_conditions: Any,
    ) -> None:
        """Append a Pass Set to the schedule of passes.

        Args:
            passes: A set of passes (a pass set) to be added to schedule. A pass set is a list of
                    passes that are controlled by the same flow controller. If a single pass is
                    provided, the pass set will only have that pass a single element.
                    It is also possible to append a
                    :class:`~qiskit.transpiler.runningpassmanager.FlowController` instance and the
                    rest of the parameter will be ignored.
            max_iteration: max number of iterations of passes.
            flow_controller_conditions: control flow plugins.

        Raises:
            TranspilerError: if a pass in passes is not a proper pass.

        See Also:
            ``RunningPassManager.add_flow_controller()`` for more information about the control
            flow plugins.
        """
        if max_iteration:
            # TODO remove this argument from append
            self.max_iteration = max_iteration

        passes = PassManager._normalize_passes(passes)
        self._pass_sets.append({"passes": passes, "flow_controllers": flow_controller_conditions})

    def replace(
        self,
        index: int,
        passes: Union[BasePass, List[BasePass]],
        max_iteration: int = None,
        **flow_controller_conditions: Any,
    ) -> None:
        """Replace a particular pass in the scheduler.

        Args:
            index: Pass index to replace, based on the position in passes().
            passes: A pass set (as defined in :py:func:`qiskit.transpiler.PassManager.append`)
                to be added to the pass manager schedule.
            max_iteration: max number of iterations of passes.
            flow_controller_conditions: control flow plugins.

        Raises:
            TranspilerError: if a pass in passes is not a proper pass or index not found.

        See Also:
            ``RunningPassManager.add_flow_controller()`` for more information about the control
            flow plugins.
        """
        if max_iteration:
            # TODO remove this argument from append
            self.max_iteration = max_iteration

        passes = PassManager._normalize_passes(passes)

        try:
            self._pass_sets[index] = {
                "passes": passes,
                "flow_controllers": flow_controller_conditions,
            }
        except IndexError as ex:
            raise TranspilerError(f"Index to replace {index} does not exists") from ex

    def remove(self, index: int) -> None:
        """Removes a particular pass in the scheduler.

        Args:
            index: Pass index to replace, based on the position in passes().

        Raises:
            TranspilerError: if the index is not found.
        """
        try:
            del self._pass_sets[index]
        except IndexError as ex:
            raise TranspilerError(f"Index to replace {index} does not exists") from ex

    def __setitem__(self, index, item):
        self.replace(index, item)

    def __len__(self):
        return len(self._pass_sets)

    def __getitem__(self, index):
        new_passmanager = PassManager(max_iteration=self.max_iteration)
        _pass_sets = self._pass_sets[index]
        if isinstance(_pass_sets, dict):
            _pass_sets = [_pass_sets]
        new_passmanager._pass_sets = _pass_sets
        return new_passmanager

    def __add__(self, other):
        if isinstance(other, PassManager):
            new_passmanager = PassManager(max_iteration=self.max_iteration)
            new_passmanager._pass_sets = self._pass_sets + other._pass_sets
            return new_passmanager
        else:
            try:
                new_passmanager = PassManager(max_iteration=self.max_iteration)
                new_passmanager._pass_sets += self._pass_sets
                new_passmanager.append(other)
                return new_passmanager
            except TranspilerError as ex:
                raise TypeError(
                    f"unsupported operand type + for {self.__class__} and {other.__class__}"
                ) from ex

    @staticmethod
    def _normalize_passes(
        passes: Union[BasePass, List[BasePass], FlowController]
    ) -> List[BasePass]:
        if isinstance(passes, FlowController):
            return passes
        if isinstance(passes, BasePass):
            passes = [passes]
        for pass_ in passes:
            if isinstance(pass_, FlowController):
                # Normalize passes in nested FlowController
                PassManager._normalize_passes(pass_.passes)
            elif not isinstance(pass_, BasePass):
                raise TranspilerError(
                    "%s is not a BasePass or FlowController instance " % pass_.__class__
                )
        return passes

    def run(
        self,
        circuits: Union[QuantumCircuit, List[QuantumCircuit]],
        output_name: str = None,
        callback: Callable = None,
    ) -> Union[QuantumCircuit, List[QuantumCircuit]]:
        """Run all the passes on the specified ``circuits``.

        Args:
            circuits: Circuit(s) to transform via all the registered passes.
            output_name: The output circuit name. If ``None``, it will be set to the same as the
                input circuit name.
            callback: A callback function that will be called after each pass execution. The
                function will be called with 5 keyword arguments::

                    pass_ (Pass): the pass being run
                    dag (DAGCircuit): the dag output of the pass
                    time (float): the time to execute the pass
                    property_set (PropertySet): the property set
                    count (int): the index for the pass execution

                The exact arguments pass expose the internals of the pass
                manager and are subject to change as the pass manager internals
                change. If you intend to reuse a callback function over
                multiple releases be sure to check that the arguments being
                passed are the same.

                To use the callback feature you define a function that will
                take in kwargs dict and access the variables. For example::

                    def callback_func(**kwargs):
                        pass_ = kwargs['pass_']
                        dag = kwargs['dag']
                        time = kwargs['time']
                        property_set = kwargs['property_set']
                        count = kwargs['count']
                        ...

        Returns:
            The transformed circuit(s).
        """
        if not self._pass_sets and output_name is None and callback is None:
            return circuits
        if isinstance(circuits, QuantumCircuit):
            return self._run_single_circuit(circuits, output_name, callback)
        if len(circuits) == 1:
            return self._run_single_circuit(circuits[0], output_name, callback)
        return self._run_several_circuits(circuits, output_name, callback)

    def _create_running_passmanager(self) -> RunningPassManager:
        running_passmanager = RunningPassManager(self.max_iteration)
        for pass_set in self._pass_sets:
            running_passmanager.append(pass_set["passes"], **pass_set["flow_controllers"])
        return running_passmanager

    @staticmethod
    def _in_parallel(circuit, pm_dill=None) -> QuantumCircuit:
        """Task used by the parallel map tools from ``_run_several_circuits``."""
        running_passmanager = dill.loads(pm_dill)._create_running_passmanager()
        result = running_passmanager.run(circuit)
        return result

    def _run_several_circuits(
        self, circuits: List[QuantumCircuit], output_name: str = None, callback: Callable = None
    ) -> List[QuantumCircuit]:
        """Run all the passes on the specified ``circuits``.

        Args:
            circuits: Circuits to transform via all the registered passes.
            output_name: The output circuit name. If ``None``, it will be set to the same as the
                input circuit name.
            callback: A callback function that will be called after each pass execution.

        Returns:
            The transformed circuits.
        """
        # TODO support for List(output_name) and List(callback)
        del output_name
        del callback

        return parallel_map(
            PassManager._in_parallel, circuits, task_kwargs={"pm_dill": dill.dumps(self)}
        )

    def _run_single_circuit(
        self, circuit: QuantumCircuit, output_name: str = None, callback: Callable = None
    ) -> QuantumCircuit:
        """Run all the passes on a ``circuit``.

        Args:
            circuit: Circuit to transform via all the registered passes.
            output_name: The output circuit name. If ``None``, it will be set to the same as the
                input circuit name.
            callback: A callback function that will be called after each pass execution.

        Returns:
            The transformed circuit.
        """
        running_passmanager = self._create_running_passmanager()
        result = running_passmanager.run(circuit, output_name=output_name, callback=callback)
        self.property_set = running_passmanager.property_set
        return result

    def draw(self, filename=None, style=None, raw=False):
        """Draw the pass manager.

        This function needs `pydot <https://github.com/erocarrera/pydot>`__, which in turn needs
        `Graphviz <https://www.graphviz.org/>`__ to be installed.

        Args:
            filename (str): file path to save image to.
            style (dict): keys are the pass classes and the values are the colors to make them. An
                example can be seen in the DEFAULT_STYLE. An ordered dict can be used to ensure
                a priority coloring when pass falls into multiple categories. Any values not
                included in the provided dict will be filled in from the default dict.
            raw (bool): If ``True``, save the raw Dot output instead of the image.

        Returns:
            Optional[PassManager]: an in-memory representation of the pass manager, or ``None``
            if no image was generated or `Pillow <https://pypi.org/project/Pillow/>`__
            is not installed.

        Raises:
            ImportError: when nxpd or pydot not installed.
        """
        return pass_manager_drawer(self, filename=filename, style=style, raw=raw)

    def passes(self) -> List[Dict[str, BasePass]]:
        """Return a list structure of the appended passes and its options.

        Returns:
            A list of pass sets, as defined in ``append()``.
        """
        ret = []
        for pass_set in self._pass_sets:
            item = {"passes": pass_set["passes"]}
            if pass_set["flow_controllers"]:
                item["flow_controllers"] = set(pass_set["flow_controllers"].keys())
            else:
                item["flow_controllers"] = {}
            ret.append(item)
        return ret


class StagedPassManager(PassManager):
    """A Pass manager pipeline built up of individual stages

    This class enables building a compilation pipeline out of fixed stages.
    Each ``StagedPassManager`` defines a list of stages which are executed in
    a fixed order, and each stage is defined as a standalone :class:`~.PassManager`
    instance. There are also ``pre_`` and ``post_`` stages for each defined stage.
    This enables easily composing and replacing different stages and also adding
    hook points to enable programmtic modifications to a pipeline. When using a staged
    pass manager you are not able to modify the individual passes and are only able
    to modify stages.

    By default instances of StagedPassManager define a typical full compilation
    pipeline from an abstract virtual circuit to one that is optimized and
    capable of running on the specified backend. The default pre-defined stages are:

    #. ``init`` - any initial passes that are run before we start embedding the circuit to the backend
    #. ``layout`` - This stage runs layout and maps the virtual qubits in the
       circuit to the physical qubits on a backend
    #. ``routing`` - This stage runs after a layout has been run and will insert any
       necessary gates to move the qubit states around until it can be run on
       backend's compuling map.
    #. ``translation`` - Perform the basis gate translation, in other words translate the gates
       in the circuit to the target backend's basis set
    #. ``optimization`` - The main optimization loop, this will typically run in a loop trying to
       optimize the circuit until a condtion (such as fixed depth) is reached.
    #. ``scheduling`` - Any hardware aware scheduling passes

    .. note::

        For backwards compatibility the relative positioning of these default
        stages will remain stable moving forward. However, new stages may be
        added to the default stage list in between current stages. For example,
        in a future release a new phase, something like ``logical_optimization``, could be added
        immediately after the existing ``init`` stage in the default stage list.
        This would preserve compatibility for pre-existing ``StagedPassManager``
        users as the relative positions of the stage are preserved so the behavior
        will not change between releases.

    These stages will be executed in order and any stage set to ``None`` will be skipped. If
    a :class:`~qiskit.transpiler.PassManager` input is being used for more than 1 stage here
    (for example in the case of a :class:`~.Pass` that covers both Layout and Routing) you will want
    to set that to the earliest stage in sequence that it covers.
    """

    invalid_stage_regex = re.compile(
        r"\s|\+|\-|\*|\/|\\|\%|\<|\>|\@|\!|\~|\^|\&|\:|\[|\]|\{|\}|\(|\)"
    )

    def __init__(self, stages=None, **kwargs):
        """Initialize a new StagedPassManager object

        Args:
            stages (List[str]): An optional list of stages to use for this
                instance. If this is not specified the default stages list
                ``['init', 'layout', 'routing', 'translation', 'optimization', 'scheduling']`` is
                used
            kwargs: The initial :class:`~.PassManager` values for any stages
                defined in ``stages``. If a argument is not defined the
                stages will default to ``None`` indicating an empty/undefined
                stage.

        Raises:
            AttributeError: If a stage in the input keyword arguments is not defined.
            ValueError: If an invalid stage name is specified.
        """
        if stages is None:
            self.stages = [
                "init",
                "layout",
                "routing",
                "translation",
                "optimization",
                "scheduling",
            ]
        else:
            invalid_stages = [
                stage for stage in stages if self.invalid_stage_regex.search(stage) is not None
            ]
            if invalid_stages:
                with io.StringIO() as msg:
                    msg.write(f"The following stage names are not valid: {invalid_stages[0]}")
                    for invalid_stage in invalid_stages[1:]:
                        msg.write(f", {invalid_stage}")
                    raise ValueError(msg.getvalue())

            self.stages = stages
        super().__init__()
        for stage in self.stages:
            pre_stage = "pre_" + stage
            post_stage = "post_" + stage
            setattr(self, pre_stage, None)
            setattr(self, stage, None)
            setattr(self, post_stage, None)
        for stage, pm in kwargs.items():
            if (
                stage not in self.stages
                and not (stage.startswith("pre_") and stage[4:] in self.stages)
                and not (stage.startswith("post_") and stage[5:] in self.stages)
            ):
                raise AttributeError(f"{stage} is not a valid stage.")
            setattr(self, stage, pm)
        self._update_passmanager()

    def _update_passmanager(self):
        self._pass_sets = []
        for stage in self.stages:
            # Add pre-stage PM
            pre_stage_pm = getattr(self, "pre_" + stage, None)
            if pre_stage_pm is not None:
                self._pass_sets.extend(pre_stage_pm._pass_sets)
            # Add stage PM
            stage_pm = getattr(self, stage, None)
            if stage_pm is not None:
                self._pass_sets.extend(stage_pm._pass_sets)
            # Add post-stage PM
            post_stage_pm = getattr(self, "post_" + stage, None)
            if post_stage_pm is not None:
                self._pass_sets.extend(post_stage_pm._pass_sets)

    def __setattr__(self, attr, value):
        super().__setattr__(attr, value)
        if (
            attr in self.stages
            or (attr.startswith("pre_") and attr[4:] not in self.stages)
            or (attr.startswith("post_") and attr[5:] not in self.stages)
        ):
            self._update_passmanager()

    def append(
        self,
        passes: Union[BasePass, List[BasePass]],
        max_iteration: int = None,
        **flow_controller_conditions: Any,
    ) -> None:
        raise NotImplementedError

    def replace(
        self,
        index: int,
        passes: Union[BasePass, List[BasePass]],
        max_iteration: int = None,
        **flow_controller_conditions: Any,
    ) -> None:
        raise NotImplementedError

    # Raise NotImplemntedError on individual pass manipulation
    def remove(self, index: int) -> None:
        raise NotImplementedError

    def __getitem(self, index):
        self._update_passmanager()
        return super().__getitem__(index)

    def __len__(self):
        self._update_passmanager()
        return super().__len__()

    def __setitem__(self, index, item):
        raise NotImplementedError

    def __add__(self, other):
        raise NotImplementedError

    def _create_running_passmanager(self) -> RunningPassManager:
        self._update_passmanager()
        return super()._create_running_passmanager()

    def passes(self) -> List[Dict[str, BasePass]]:
        self._update_passmanager()
        return super().passes()

    def run(
        self,
        circuits: Union[QuantumCircuit, List[QuantumCircuit]],
        output_name: str = None,
        callback: Callable = None,
    ) -> Union[QuantumCircuit, List[QuantumCircuit]]:
        self._update_passmanager()
        return super().run(circuits, output_name, callback)
