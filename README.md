# HDL Runner

A Python-based framework for running and testing hardware designs using industry-standard simulators and [cocotb](https://www.cocotb.org/) for testbenches. HDL Runner supports designs written in [Amaranth HDL](https://amaranth-lang.org/) (formerly nMigen), as well as pure Verilog or VHDL sources.

HDL Runner automates the process of converting Amaranth designs to Verilog (if needed), running simulations with various backends, and integrating with cocotb for Python-based testbenches.

## Features

- **Simulator Abstraction:** Supports multiple simulators (see [Currently Supported Simulators](#currently-supported-simulators)).
- **Amaranth Integration (Optional):** Seamlessly converts Amaranth designs to Verilog for simulation, or you can use your own Verilog/VHDL sources directly.
- **cocotb Integration:** Write testbenches in Python using cocotb.
- **Waveform Generation:** Supports VCD and FST waveform outputs.
- **Flexible Port Handling:** When using Amaranth, you must specify the top-level ports. You can pass lists, dictionaries, tuples, Amaranth Records, or other structures, and HDL Runner will automatically "unwrap" them to extract the actual signals to expose as ports.
- **Parameterized Builds:** Pass parameters and extra environment variables to simulations.
- **Temporary or Custom Build Directories:** Use temporary directories or specify your own.

## Installation

Install HDL Runner and its dependencies using pip:

```sh
pip install hdl_runner
```

All required Python dependencies (including Amaranth HDL and cocotb) are installed automatically. You will need at least one supported simulator installed and available in your PATH.

If you want to run tests using the `test_` functions, you may want to install `pytest`:

```sh
pip install pytest
```

## Usage

### 1. Using Amaranth HDL

#### Define Your Amaranth Module

```python
from amaranth import *

class Adder(Elaboratable):
    def __init__(self, width, domain='sync'):
        self.width = width
        self.domain = domain
        self.a = Signal(width)
        self.b = Signal(width)
        self.o = Signal(width + 1)

    def elaborate(self, platform):
        m = Module()
        m.d[self.domain] += self.o.eq(self.a + self.b)
        return m
```

#### Write a cocotb Testbench

```python
import cocotb
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.clock import Clock

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
    # ... your test logic ...
```

#### Run the Simulation

Use the `run` function from `hdl_runner.runner` to build and run your simulation:

```python
from hdl_runner.runner import run

def test():
    adder = Adder(width=8)
    run(
        adder,
        ports=[adder.a, adder.b, adder.o],  # Required for Amaranth modules
        waveform_file='adder.fst',
        simulator='verilator',  # or 'icarus', 'ghdl'
    )

if __name__ == '__main__':
    test()
```

**Note:** The `ports` argument is required when using an Amaranth module. You can pass a list, tuple, dictionary, Amaranth Record, or other nested structures; HDL Runner will recursively extract the actual signals to use as ports.

### 2. Using Verilog or VHDL Sources Directly

You can also use HDL Runner with your own Verilog or VHDL sources, without Amaranth:

```python
from hdl_runner.runner import run

def test():
    run(
        module=None,
        verilog_sources=['my_design.v'],
        vhdl_sources=[],  # or provide VHDL files
        toplevel='my_top_module',  # Name of the top-level module/entity in your HDL
        simulator='icarus',
        waveform_file='output.vcd',
    )

if __name__ == '__main__':
    test()
```

- If you provide `toplevel`, HDL Runner will use that as the top-level module/entity from your HDL sources.
- If you provide an Amaranth module, `toplevel` is optional and will default to the Amaranth module.

### 3. Running Your Test

You can run your test script directly with Python:

```sh
python test_adder.py
```

Or, if you use `pytest` for test discovery:

```sh
python -m pytest test_adder.py
```

## Currently Supported Simulators

- **Verilator** (`simulator='verilator'`)
- **Icarus Verilog** (`simulator='icarus'`)
- **GHDL** (`simulator='ghdl'`)
- **NVC** (`simulator='nvc'`)

More simulators may be supported in the future.

## Options

- `module`: Amaranth Elaboratable module (optional, use `None` for pure HDL sources).
- `ports`: List/tuple/dict/Record of top-level signals to expose (required for Amaranth modules, ignored for pure HDL).
- `verilog_sources`, `vhdl_sources`: Additional HDL sources.
- `toplevel`: Name of the top-level module/entity in your HDL sources (required if not using Amaranth).
- `waveform_file`: Output file for simulation waveforms (`.vcd` or `.fst`).
- `parameters`: Dictionary of parameters to pass to the design.
- `extra_env`: Extra environment variables for the simulator.
- `build_dir`: Directory for build artifacts (default: temporary).
- `random_seed`: Set simulation seed for reproducibility.
- `timescale`: Tuple for HDL timescale (default: `('1ns', '1ps')`).

## Development

Clone the repository and install in editable mode:

```sh
git clone https://github.com/AlanVek/hdl_runner.git
pip install -e hdl_runner/
```

## License

MIT License

---

**Note:** This project is not affiliated with the Amaranth HDL or cocotb projects. Please ensure you have the required simulators and Python packages installed.
