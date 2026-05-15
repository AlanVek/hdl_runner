from amaranth import *

class Adder(Elaboratable):
    def __init__(self, width, domain = 'sync'):
        if not isinstance(width, int) or width <= 0:
            raise ValueError(f"Invalid argument for 'width': {width}")

        self.width  = width
        self.domain = domain

        self.a      = Signal(width)
        self.b      = Signal(width)
        self.o      = Signal(width + 1)

    def elaborate(self, platform):
        m = Module()
        sync = m.d[self.domain]

        sync += self.o.eq(self.a + self.b)

        return m

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.clock import Clock
import os
from random import getrandbits

async def init_test(dut):
    cocotb.start_soon(Clock(dut.clk, 10, 'ns').start())

    dut.a.value = 0
    dut.b.value = 0

    dut.rst.value = 1
    await ClockCycles(dut.clk, 10)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 10)


@cocotb.test()
async def adder_test(dut):
    await init_test(dut)

    N_TESTS = int(os.getenv('N_TESTS', 100))

    last = None
    for i in range(N_TESTS):
        a = getrandbits(len(dut.a))
        b = getrandbits(len(dut.b))

        dut.a.value = a
        dut.b.value = b
        await RisingEdge(dut.clk)

        if last is not None:
            assert last == dut.o.value, f"Test failed: {last} != {dut.o.value}"

        last = a + b

import pytest
from pathlib import Path
from hdl_runner import run

EXAMPLES_DIR = Path(__file__).parent

def generate_tests(language, extension, backends, simulators, **kwargs):
    @pytest.mark.parametrize('width', [1, 2, 4, 8])
    @pytest.mark.parametrize('backend', backends)
    @pytest.mark.parametrize('simulator', simulators)
    def test(width, backend, simulator):
        if backend is None:
            m = None
            toplevel = 'Adder'
            sources = list(EXAMPLES_DIR.glob(f'*.{extension}'))
            parameters = {'size': width}
            ports = None
        else:
            m = Adder(width)
            toplevel = sources = parameters = None
            ports = [m.a, m.b, m.o]

        run(
            m,
            ports = ports,
            waveform_file = f'adder_{width}_{simulator}{f"_{backend}" or ""}_{language}.fst',
            toplevel = toplevel,
            **{f'{language}_sources': sources},
            parameters = parameters,
            simulator = simulator,
            backend = backend,
            **kwargs,
        )

    return test