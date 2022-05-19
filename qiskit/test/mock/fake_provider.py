# This code is part of Qiskit.
#
# (C) Copyright IBM 2019.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

# pylint: disable=wildcard-import,unused-argument

"""
Fake provider class that provides access to fake backends.
"""

from qiskit.providers.provider import ProviderV1
from qiskit.providers.exceptions import QiskitBackendNotFoundError

from .backends import *
from .fake_qasm_simulator import FakeQasmSimulator
from .fake_openpulse_2q import FakeOpenPulse2Q
from .fake_openpulse_3q import FakeOpenPulse3Q


class FakeProvider(ProviderV1):
    """Dummy provider just for testing purposes.

    Only filtering backends by name is implemented.
    """

    def get_backend(self, name=None, **kwargs):
        backend = self._backends[0]
        if name:
            filtered_backends = [backend for backend in self._backends if backend.name() == name]
            if not filtered_backends:
                raise QiskitBackendNotFoundError()

            backend = filtered_backends[0]

        return backend

    def backends(self, name=None, **kwargs):
        return self._backends

    def __init__(self):
        self._backends = [
            FakeAlmaden(),
            FakeArmonk(),
            FakeAthens(),
            FakeBelem(),
            FakeBoeblingen(),
            FakeBogota(),
            FakeBrooklyn(),
            FakeBurlington(),
            FakeCambridge(),
            FakeCambridgeAlternativeBasis(),
            FakeCasablanca(),
            FakeEssex(),
            FakeGuadalupe(),
            FakeJakarta(),
            FakeJohannesburg(),
            FakeLagos(),
            FakeLima(),
            FakeLondon(),
            FakeManila(),
            FakeManhattan(),
            FakeMelbourne(),
            FakeMontreal(),
            FakeMumbai(),
            FakeOpenPulse2Q(),
            FakeOpenPulse3Q(),
            FakeOurense(),
            FakeParis(),
            FakePoughkeepsie(),
            FakeQasmSimulator(),
            FakeQuito(),
            FakeRochester(),
            FakeRome(),
            FakeRueschlikon(),
            FakeSantiago(),
            FakeSingapore(),
            FakeSydney(),
            FakeTenerife(),
            FakeTokyo(),
            FakeToronto(),
            FakeValencia(),
            FakeVigo(),
            FakeYorktown(),
        ]

        super().__init__()
