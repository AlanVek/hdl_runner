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
def test(width):

    from glob import glob

    run(
        waveform_file = 'adder_icarus_verilog.vcd',
        toplevel = 'Adder',
        verilog_sources = glob(os.path.join(os.path.dirname(os.path.dirname(__file__)), '*.v')),
        parameters = {'size': width},
        simulator = 'icarus',
    )

if __name__ == '__main__':
    test(8)