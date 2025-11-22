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
from hdl_runner.runner import run
import os
from random import getrandbits
import pytest

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

@pytest.mark.parametrize('width', [1, 2, 4, 8])
@pytest.mark.parametrize('backend', ['celosia', 'amaranth'])
def test(width, backend):
    adder = Adder(width, domain = 'sync')
    run(
        adder,
        ports = [adder.a, adder.b, adder.o],
        waveform_file = 'adder_icarus_amaranth.fst',
        simulator='icarus',
        backend = backend,
    )

if __name__ == '__main__':
    test(8, 'amaranth')