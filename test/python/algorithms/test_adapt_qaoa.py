# This code is part of Qiskit.
#
# (C) Copyright IBM 2018, 2021.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

""" Test AdaptQAOA """

import math
import unittest
from functools import reduce
from itertools import combinations_with_replacement, permutations, product
from test.python.algorithms import QiskitAlgorithmsTestCase

import random
import numpy as np
import networkx as nx
import retworkx as rx
from ddt import ddt, idata, unpack
from qiskit import BasicAer, QuantumCircuit, QuantumRegister
from qiskit.algorithms import AdaptQAOA
from qiskit.algorithms.optimizers import COBYLA, NELDER_MEAD
from qiskit.circuit.library import IGate, XGate, YGate, ZGate
from qiskit.opflow import I, PauliSumOp, X, Y, Z
from qiskit.quantum_info import Pauli
from qiskit.utils import QuantumInstance, algorithm_globals


def _string_to_qiskit(qstring):
    qis_dict = {"I": I, "X": X, "Y": Y, "Z": Z}

    if all(x == qstring[0] for x in qstring):
        gate = qstring[0]
        list_string = [i * "I" + gate + (len(qstring) - i - 1) * "I" for i in range(len(qstring))]
        return sum([reduce(lambda a, b: a ^ b, [qis_dict[char.upper()] for char in x]) for x in list_string])
    return reduce(lambda a, b: a ^ b, [qis_dict[char.upper()] for char in qstring])


def _create_mixer_pool(num_q, add_multi, circ):
    """Compute the mixer pool
    Args:
        num_q (int): number of qubits
        add_multi (bool): whether to add multi qubit gates to the mixer pool
        circ (bool): if output mixer pool in form of list of circuits instead of list of operators
        parameterize (bool): if the circuit mixers should be parameterized

    Returns:
        list: all possible combinations of mixers
    """
    mixer_pool = ["X" * num_q]

    mixer_pool.append("Y" * num_q)
    mixer_pool += [i * "I" + 'X' + (num_q - i - 1)
                    * "I" for i in range(num_q)]
    mixer_pool += [i * "I" + 'Y' + (num_q - i-1)
                    * "I" for i in range(num_q)]
    
    if add_multi:
        indicies = list(permutations(range(num_q), 2))
        indicies = list(set(tuple(sorted(x)) for x in indicies))
        combos = list(combinations_with_replacement(['X', 'Y', 'Z'], 2))
        full_multi = list(product(indicies, combos))
        for item in full_multi:
            iden_str = list("I" * num_q)
            iden_str[item[0][0]] = item[1][0]
            iden_str[item[0][1]] = item[1][1]
            mixer_pool.append(''.join(iden_str))

    mixer_circ_list = []
    for mix_str in mixer_pool:
        if circ:
            # TODO: do the circuits need to be parameterised?
            qr = QuantumRegister(num_q)
            qc = QuantumCircuit(qr)
            for i, mix in enumerate(mix_str):
                qiskit_dict = {"I": IGate(), "X": XGate(), "Y": YGate(), "Z": ZGate()}

                mix_qis_gate = qiskit_dict[mix]
                qc.append(mix_qis_gate, [i])
                mixer_circ_list.append(qc)
        else:
            op = _string_to_qiskit(mix_str)
            mixer_circ_list.append(op)
    return mixer_circ_list

W1 = np.array([[0, 1, 0, 1], [1, 0, 1, 0], [0, 1, 0, 1], [1, 0, 1, 0]])
P1 = 1
M1 = _create_mixer_pool(num_q=2, add_multi=True, circ=False)
S1 = {"0101", "1010"}

W2 = np.array(
    [
        [0.0, 8.0, -9.0, 0.0],
        [8.0, 0.0, 7.0, 9.0],
        [-9.0, 7.0, 0.0, -8.0],
        [0.0, 9.0, -8.0, 0.0],
    ]
)
P2 = 1
M2 = None
S2 = {"1011", "0100"}

CUSTOM_SUPERPOSITION = [1 / math.sqrt(15)] * 15 + [0]


@ddt
class TestAdaptQAOA(QiskitAlgorithmsTestCase):
    """Test AdaptQAOA with MaxCut."""

    def setUp(self):
        super().setUp()
        self.seed = 10598
        algorithm_globals.random_seed = self.seed

        self.qasm_simulator = QuantumInstance(
            BasicAer.get_backend("qasm_simulator"),
            shots=4096,
            seed_simulator=self.seed,
            seed_transpiler=self.seed,
        )
        self.statevector_simulator = QuantumInstance(
            BasicAer.get_backend("statevector_simulator"),
            seed_simulator=self.seed,
            seed_transpiler=self.seed,
        )

    @idata(
        [
            [W1, P1, M1, S1, False],
            [W2, P2, M2, S2, False],
            [W1, P1, M1, S1, True],
            [W2, P2, M2, S2, True],
        ]
    )
    @unpack
    def test_adapt_qaoa(self, w, prob, m, solutions, convert_to_matrix_op):
        """AdaptQAOA test"""
        self.log.debug("Testing %s-step AdaptQAOA with MaxCut on graph\n%s", prob, w)

        qubit_op, _ = self._get_operator(w)
        if convert_to_matrix_op:
            qubit_op = qubit_op.to_matrix_op()

        adapt_qaoa = AdaptQAOA(
            optimizer=COBYLA(), reps=prob, mixer_pool=m, quantum_instance=self.statevector_simulator
        )
        result = adapt_qaoa.compute_minimum_eigenvalue(operator=qubit_op)
        x = self._sample_most_likely(result.eigenstate)
        graph_solution = self._get_graph_solution(x)
        self.assertIn(graph_solution, solutions)

    @idata(
        [
            [W1, P1, S1, False],
            [W2, P2, S2, False],
            [W1, P1, S1, True],
            [W2, P2, S2, True],
        ]
    )
    @unpack
    def test_adapt_qaoa_qc_mixer(self, w, prob, solutions, convert_to_matrix_op):
        """AdaptQAOA test with a mixer as a circuit"""
        self.log.debug(
            "Testing %s-step AdaptQAOA with MaxCut on graph with "
            "a mixer as a parameterized circuit\n%s",
            prob,
            w,
        )

        optimizer = optimizer = COBYLA()
        qubit_op, _ = self._get_operator(w)
        if convert_to_matrix_op:
            qubit_op = qubit_op.to_matrix_op()

        num_qubits = qubit_op.num_qubits
        mixer = _create_mixer_pool(num_q=num_qubits, add_multi=True, circ=True)

        adapt_qaoa = AdaptQAOA(
            optimizer=optimizer,
            reps=prob,
            mixer_pool=mixer,
            quantum_instance=self.statevector_simulator,
        )

        result = adapt_qaoa.compute_minimum_eigenvalue(operator=qubit_op)
        x = self._sample_most_likely(result.eigenstate)
        graph_solution = self._get_graph_solution(x)
        self.assertIn(graph_solution, solutions)

    def test_adapt_qaoa_qc_mixer_type(self):
        """AdaptQAOA test with no mixer_pool specified but mixer_pool_type is specified"""
        qubit_op, _ = self._get_operator(W1)

        adapt_qaoa = AdaptQAOA(
            optimizer=COBYLA(),
            reps=2,
            mixer_pool_type="multi",
            quantum_instance=self.statevector_simulator,
        )

        result = adapt_qaoa.compute_minimum_eigenvalue(operator=qubit_op)
        x = self._sample_most_likely(result.eigenstate)
        self.log.debug(x)
        graph_solution = self._get_graph_solution(x)
        self.assertIn(graph_solution, S1)

    def test_adapt_qaoa_qc_mixer_many_parameters(self):
        """AdaptQAOA test with a mixer as a parameterized circuit with the num of parameters > 1."""
        qubit_op, _ = self._get_operator(W1)

        num_qubits = qubit_op.num_qubits
        # TODO: differentiate between this function (>1 params) and
        # prev function (=1 params) or delete one
        mixer = _create_mixer_pool(num_qubits, add_multi=True, circ=True)

        adapt_qaoa = AdaptQAOA(
            optimizer=COBYLA(),
            reps=2,
            mixer_pool=mixer,
            quantum_instance=self.statevector_simulator,
        )

        result = adapt_qaoa.compute_minimum_eigenvalue(operator=qubit_op)
        x = self._sample_most_likely(result.eigenstate)
        self.log.debug(x)
        graph_solution = self._get_graph_solution(x)
        self.assertIn(graph_solution, S1)

    def test_adapt_qaoa_qc_mixer_no_parameters(self):
        """AdaptQAOA test with a mixer pool as a list of circuits with zero parameters."""
        qubit_op, _ = self._get_operator(W1)

        num_qubits = qubit_op.num_qubits
        mixer = _create_mixer_pool(num_qubits, add_multi=True, circ=True)

        adapt_qaoa = AdaptQAOA(
            optimizer=COBYLA(),
            reps=1,
            mixer_pool=mixer,
            quantum_instance=self.statevector_simulator,
        )

        result = adapt_qaoa.compute_minimum_eigenvalue(operator=qubit_op)
        # we just assert that we get a result, it is not meaningful.
        self.assertIsNotNone(result.eigenstate)

    def test_change_operator_size(self):
        """AdaptQAOA change operator size test"""
        qubit_op, _ = self._get_operator(
            np.array([[0, 1, 0, 1], [1, 0, 1, 0], [0, 1, 0, 1], [1, 0, 1, 0]])
        )
        adapt_qaoa = AdaptQAOA(
            optimizer=COBYLA(), reps=1, quantum_instance=self.statevector_simulator
        )

        result = adapt_qaoa.compute_minimum_eigenvalue(operator=qubit_op)
        x = self._sample_most_likely(result.eigenstate)
        graph_solution = self._get_graph_solution(x)
        with self.subTest(msg="AdaptQAOA 4x4"):
            self.assertIn(graph_solution, {"0101", "1010"})

        qubit_op, _ = self._get_operator(
            np.array(
                [
                    [0, 1, 0, 1, 0, 1],
                    [1, 0, 1, 0, 1, 0],
                    [0, 1, 0, 1, 0, 1],
                    [1, 0, 1, 0, 1, 0],
                    [0, 1, 0, 1, 0, 1],
                    [1, 0, 1, 0, 1, 0],
                ]
            )
        )

        result = adapt_qaoa.compute_minimum_eigenvalue(operator=qubit_op)
        x = self._sample_most_likely(result.eigenstate)
        graph_solution = self._get_graph_solution(x)
        with self.subTest(msg="AdaptQAOA 6x6"):
            self.assertIn(graph_solution, {"010101", "101010"})

    @idata([[W2, S2, None], [W2, S2, [0.0, 0.0]], [W2, S2, [1.0, 0.8]]])
    @unpack
    def test_adapt_qaoa_initial_point(self, w, solutions, init_pt):
        """Check first parameter value used is initial point as expected"""
        qubit_op, _ = self._get_operator(w)

        first_pt = []

        def cb_callback(eval_count, parameters, mean, std):
            nonlocal first_pt
            if eval_count == 1:
                first_pt = list(parameters)

        adapt_qaoa = AdaptQAOA(
            optimizer=COBYLA(),
            initial_point=init_pt,
            callback=cb_callback,
            quantum_instance=self.statevector_simulator,
        )

        result = adapt_qaoa.compute_minimum_eigenvalue(operator=qubit_op)
        x = self._sample_most_likely(result.eigenstate)
        graph_solution = self._get_graph_solution(x)

        with self.subTest("Initial Point"):
            # If None the preferred random initial point of QAOA variational form
            if init_pt is None:
                self.assertLess(result.eigenvalue.real, -0.97)
            else:
                self.assertListEqual(init_pt, first_pt)

        with self.subTest("Solution"):
            self.assertIn(graph_solution, solutions)

    @idata([[W2, None], [W2, [1.0] + 15 * [0.0]], [W2, CUSTOM_SUPERPOSITION]])
    @unpack
    def test_adapt_qaoa_initial_state(self, w, init_state):
        """AdaptQAOA initial state test"""
        optimizer = COBYLA()
        qubit_op, _ = self._get_operator(w)

        init_pt = np.asarray([0.0, 0.0])  # Avoid generating random initial point

        if init_state is None:
            initial_state = None
        else:
            initial_state = QuantumCircuit(QuantumRegister(4, "q"))
            initial_state.initialize(init_state, initial_state.qubits)

        zero_init_state = QuantumCircuit(QuantumRegister(qubit_op.num_qubits, "q"))
        adapt_qaoa_zero_init_state = AdaptQAOA(
            optimizer=optimizer,
            initial_state=zero_init_state,
            initial_point=init_pt,
            quantum_instance=self.statevector_simulator,
        )
        adapt_qaoa = AdaptQAOA(
            optimizer=optimizer,
            initial_state=initial_state,
            initial_point=init_pt,
            quantum_instance=self.statevector_simulator,
        )

        cost_op = self._max_cut_hamiltonian(D=3, nq=4)

        adapt_qaoa.compute_minimum_eigenvalue(cost_op)
        adapt_qaoa_zero_init_state.compute_minimum_eigenvalue(cost_op)

        zero_circuits = adapt_qaoa_zero_init_state.construct_circuit(init_pt, qubit_op)
        custom_circuits = adapt_qaoa.construct_circuit(init_pt, qubit_op)

        self.assertEqual(len(zero_circuits), len(custom_circuits))

        for zero_circ, custom_circ in zip(zero_circuits, custom_circuits):

            z_length = len(zero_circ.data)
            c_length = len(custom_circ.data)

            self.assertGreaterEqual(c_length, z_length)
            self.assertTrue(zero_circ.data == custom_circ.data[-z_length:])

            custom_init_qc = QuantumCircuit(custom_circ.num_qubits)
            custom_init_qc.data = custom_circ.data[0 : c_length - z_length]

            if initial_state is None:
                original_init_qc = QuantumCircuit(qubit_op.num_qubits)
                original_init_qc.h(range(qubit_op.num_qubits))
            else:
                original_init_qc = initial_state

            job_init_state = self.statevector_simulator.execute(original_init_qc)
            job_qaoa_init_state = self.statevector_simulator.execute(custom_init_qc)

            statevector_original = job_init_state.get_statevector(original_init_qc)
            statevector_custom = job_qaoa_init_state.get_statevector(custom_init_qc)

            self.assertListEqual(statevector_original.tolist(), statevector_custom.tolist())

    def test_adapt_qaoa_random_initial_point(self):
        """AdaptQAOA random initial point"""
        w = rx.adjacency_matrix(
            rx.undirected_gnp_random_graph(5, 0.5, seed=algorithm_globals.random_seed)
        )
        qubit_op, _ = self._get_operator(w)

        adapt_qaoa = AdaptQAOA(
            optimizer=NELDER_MEAD(disp=True), reps=1, quantum_instance=self.qasm_simulator
        )

        result = adapt_qaoa.compute_minimum_eigenvalue(operator=qubit_op)

        self.assertLess(result.eigenvalue.real, -0.97)

    def _get_operator(self, weight_matrix):
        """Generate Hamiltonian for the max-cut problem of a graph.

        Args:
            weight_matrix (numpy.ndarray) : adjacency matrix.

        Returns:
            PauliSumOp: operator for the Hamiltonian
            float: a constant shift for the obj function.

        """
        num_nodes = weight_matrix.shape[0]
        pauli_list = []
        shift = 0
        for i in range(num_nodes):
            for j in range(i):
                if weight_matrix[i, j] != 0:
                    x_p = np.zeros(num_nodes, dtype=bool)
                    z_p = np.zeros(num_nodes, dtype=bool)
                    z_p[i] = True
                    z_p[j] = True
                    pauli_list.append([0.5 * weight_matrix[i, j], Pauli((z_p, x_p))])
                    shift -= 0.5 * weight_matrix[i, j]
        opflow_list = [(pauli[1].to_label(), pauli[0]) for pauli in pauli_list]
        return PauliSumOp.from_list(opflow_list), shift

    def _get_graph_solution(self, x: np.ndarray) -> str:
        """Get graph solution from binary string.

        Args:
            x : binary string as numpy array.

        Returns:
            a graph solution as string.
        """

        return "".join([str(int(i)) for i in 1 - x])

    def _sample_most_likely(self, state_vector):
        """Compute the most likely binary string from state vector.
        Args:
            state_vector (numpy.ndarray or dict): state vector or counts.

        Returns:
            numpy.ndarray: binary string as numpy.ndarray of ints.
        """
        n = int(np.log2(state_vector.shape[0]))
        k = np.argmax(np.abs(state_vector))
        x = np.zeros(n)
        for i in range(n):
            x[i] = k % 2
            k >>= 1
        return x

    def _max_cut_hamiltonian(self, D, nq):
        """ Calculates the Hamiltonian for a specific max cut graph.
        Args: 
            D (int): connectivity. 
            nq (int): number of qubits.

        Returns:
            PauliSumOp: Hamiltonian of graph.
        """
        G = nx.random_regular_graph(D, nq, seed=1234) # connectivity, vertices
        for (u, v) in G.edges():
            G.edges[u,v]['weight'] = random.randint(0,1000)/1000
        w = np.zeros([nq,nq])
        for i in range(nq):
            for j in range(nq):
                temp = G.get_edge_data(i,j,default=0)
                if temp != 0:
                    w[i,j] = temp['weight']
        hc_pauli, _ = self._get_operator(w)
        return hc_pauli


if __name__ == "__main__":
    unittest.main()
