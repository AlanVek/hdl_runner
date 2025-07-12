import os
import tempfile
import shutil
import inspect
import warnings
from amaranth.back import verilog
import find_libpython
import sys
import cocotb
from amaranth import Record, Signal

with warnings.catch_warnings():
    warnings.filterwarnings("ignore")
    from cocotb.runner import get_runner
    from amaranth.hdl.ast import SignalDict, SignalKey

def open_ports(ports) -> list:
    """
    Recursively unwraps and collects all Amaranth Signals from the given ports structure.
    Accepts lists, tuples, dicts, Records, SignalDicts, SignalKeys, etc.

    Args:
        ports: The ports structure to unwrap.

    Returns:
        List of Signal objects.
    """

    if hasattr(ports, 'as_value') and callable(ports.as_value):
        ports = ports.as_value()

    if isinstance(ports, Signal):
        return [ports]

    res = []

    if isinstance(ports, Record):
        ports = ports.fields
    elif isinstance(ports, SignalKey):
        ports = [ports.signal]

    if isinstance(ports, dict):
        ports = ports.values()
    elif isinstance(ports, SignalDict):
        ports = ports.keys()

    try:
        for pin in ports:
            res += open_ports(pin)
    except TypeError:
        raise ValueError("Invalid ports received!") from None

    return res

class Simulator:
    """
    Base class for HDL simulators.
    Handles build and run logic, environment setup, and waveform management.
    """
    name = None
    valid_waveforms = ['vcd', 'fst']

    def __init__(
        self,
        hdl_toplevel: str,
        caller_file: str,
        verilog_sources: list = None,
        vhdl_sources: list = None,
        parameters: dict = None,
        extra_env: dict = None,
        waveform_file: str = None,
        random_seed: int = None,
        directory: str = '.',
        timescale: tuple = ('1ns', '1ps'),
    ):
        """
        Args:
            hdl_toplevel: Name of the top-level module/entity.
            caller_file: Path to the Python file invoking the runner.
            verilog_sources: List of Verilog source files.
            vhdl_sources: List of VHDL source files.
            parameters: Dictionary of parameters to pass to the design.
            extra_env: Extra environment variables for the simulator.
            waveform_file: Output file for simulation waveforms.
            random_seed: Seed for simulation randomness.
            directory: Build directory.
            timescale: HDL timescale as a tuple (e.g., ('1ns', '1ps')).
        """
        if verilog_sources is None:
            verilog_sources = []

        if vhdl_sources is None:
            vhdl_sources = []

        if extra_env is None:
            extra_env = {}

        if parameters is None:
            parameters = {}

        self.hdl_toplevel       = hdl_toplevel
        self.caller_file        = caller_file
        self.verilog_sources    = verilog_sources
        self.vhdl_sources       = vhdl_sources
        self.parameters         = parameters
        self.extra_env          = extra_env
        self.waveform_file      = waveform_file
        self.random_seed        = random_seed
        self.directory          = directory
        self.timescale          = timescale

        self.test_module        = os.path.splitext(os.path.basename(caller_file))[0]
        self.wave_name          = waveform_file
        self.has_waves          = waveform_file is not None
        self.build_args         = []
        self.test_args          = []
        self.plusargs           = []
        self.waveform_format    = None

        if waveform_file is not None:
            extension = os.path.splitext(waveform_file)[-1][1:]
            self.waveform_format = extension

            if extension not in self.valid_waveforms:
                raise ValueError(f"Invalid extension for waveform: {extension}. Supported extensions are: {' '.join(self.valid_waveforms)}")

    def _set_env_workaround(self):
        """
        Workaround to set up the simulation environment for cocotb.
        """
        def _set_env(runner):
            for e in os.environ:
                runner.env[e] = os.environ[e]

            if "LIBPYTHON_LOC" not in runner.env:
                libpython_path = find_libpython.find_libpython()
                if not libpython_path:
                    raise ValueError(
                        "Unable to find libpython, please make sure the appropriate libpython is installed"
                    )
                runner.env["LIBPYTHON_LOC"] = libpython_path

            runner.env["PATH"] += os.pathsep + cocotb.config.libs_dir
            runner.env["PYTHONPATH"] = os.pathsep.join(sys.path + [os.path.dirname(self.caller_file)])
            # runner.env["PYTHONHOME"] = sys.base_prefix
            runner.env["TOPLEVEL"] = runner.sim_hdl_toplevel
            runner.env["MODULE"] = runner.test_module

        self.runner._set_env = _set_env.__get__(self.runner)

    def _pre_build(self):
        """
        Prepare the simulator runner and environment before building.
        """
        self.runner = get_runner(self.name)
        self._set_env_workaround()

    def _pre_run(self):
        """
        Hook for subclasses to run logic before simulation.
        """
        return

    def build(self):
        """
        Build the simulation using the selected simulator.
        """
        self._pre_build()
        self.runner.build(
            verilog_sources = self.verilog_sources,
            vhdl_sources    = self.vhdl_sources,
            hdl_toplevel    = self.hdl_toplevel,
            waves           = self.has_waves,
            timescale       = self.timescale,
            build_dir       = self.directory,
            build_args      = self.build_args,
            parameters      = self.parameters,
        )

    def run(self):
        """
        Run the simulation and handle waveform output and errors.
        """
        self._pre_run()

        err_msg = None
        try:
            self.runner.test(
                hdl_toplevel    = self.hdl_toplevel,
                test_module     = self.test_module,
                timescale       = self.timescale,
                waves           = self.has_waves,
                build_dir       = self.directory,
                test_dir        = self.directory,
                test_args       = self.test_args,
                plusargs        = self.plusargs,
                seed            = self.random_seed,
                extra_env       = self.extra_env,
            )
        except BaseException as e:
            err_msg = str(e)

        if self.wave_name is not None:
            wave = os.path.join(self.directory, self.wave_name)
            if os.path.isfile(wave):
                shutil.copy2(wave, self.waveform_file)
            else:
                warnings.warn(f"Failed to find waveform output file: {wave}", stacklevel=2)

        if err_msg is not None:
            raise RuntimeError(f"Test failed: {err_msg}")

    def build_and_run(self):
        """
        Build and run the simulation in sequence.
        """
        self.build()
        self.run()

class Icarus(Simulator):
    """
    Icarus Verilog simulator integration.
    """
    name = 'icarus'

    def _pre_build(self):
        """
        Prepare Icarus-specific build arguments and waveform handling.
        """
        super()._pre_build()

        # Workaround for uninitialized registers
        self.build_args.append('-g2005')

        if self.has_waves:
            self.wave_name = f'{self.hdl_toplevel}.fst'
            if self.waveform_format == 'vcd':
                self.plusargs.append('-vcd')

    def _pre_run(self):
        """
        Prepare Icarus-specific run logic.
        """
        super()._pre_run()

        # Workaround to export VCD
        if self.waveform_format != 'fst':
            self.has_waves = False

class Verilator(Simulator):
    """
    Verilator simulator integration.
    """
    name = 'verilator'

    def _pre_build(self):
        """
        Prepare Verilator-specific build and test arguments.
        """
        super()._pre_build()
        self.build_args.append('--Wno-fatal')

        if self.has_waves:
            extra_args = ['--trace-structs']
            self.wave_name = f'dump.{self.waveform_format}'
            if self.waveform_format == 'fst':
                extra_args.append('--trace-fst')

            self.build_args.extend(extra_args)
            self.test_args.extend(extra_args)

class Ghdl(Simulator):
    """
    GHDL simulator integration.
    """
    name = 'ghdl'

    def _pre_build(self):
        """
        Prepare GHDL-specific build arguments and waveform handling.
        """
        super()._pre_build()
        self.hdl_toplevel = self.hdl_toplevel.lower()

        if self.has_waves:
            self.plusargs.append(f'--{self.waveform_format}={self.waveform_file}')

def run(
    module = None,
    ports = None,
    waveform_file = None,
    verilog_sources = None,
    vhdl_sources = None,
    toplevel = None,
    simulator: str = 'icarus',
    random_seed: int = None,
    extra_env: dict = None,
    build_dir: str = None,
    parameters: dict = None,
    platform = None,
    vcd_file: str = None, # For backwards compatibility
    timescale: tuple = ('1ns', '1ps'),
):
    """
    Main entry point to build and run a simulation.

    Args:
        module: Amaranth Elaboratable module (optional).
        ports: List/tuple/dict/Record of top-level signals to expose (required for Amaranth modules).
        waveform_file: Output file for simulation waveforms (.vcd or .fst).
        verilog_sources: List of Verilog source files.
        vhdl_sources: List of VHDL source files.
        toplevel: Name of the top-level module/entity in HDL sources (required if not using Amaranth).
        simulator: Simulator backend to use ('icarus', 'verilator', 'ghdl').
        random_seed: Seed for simulation randomness.
        extra_env: Extra environment variables for the simulator.
        build_dir: Directory for build artifacts (default: temporary).
        parameters: Dictionary of parameters to pass to the design.
        platform: Optional Amaranth platform for conversion.
        vcd_file: Deprecated, use waveform_file instead.
        timescale: HDL timescale as a tuple.
    """
    _simulators = [
        Icarus,
        Verilator,
        Ghdl,
    ]

    simulators = {sim.name: sim for sim in _simulators}

    caller_file = os.path.abspath(inspect.stack()[1].filename)

    if verilog_sources is None:
        verilog_sources = []

    if ports is None:
        ports = []

    module_name = 'amaranth_output'
    if toplevel is None:
        toplevel = module_name

        if not module:
            raise ValueError("Top-level name must be provided if no Amaranth module is given")

    extra_sources = {}
    if platform is not None and getattr(platform, 'extra_files', {}):
        for n, content in platform.extra_files.items():
            if isinstance(content, str):
                content = content.encode('utf-8')
            elif not isinstance(content, bytes):
                raise ValueError(f"Invalid extra file type: {type(content)}")
            extra_sources[n] = content

    if module is None and not (verilog_sources or vhdl_sources or extra_sources):
        raise ValueError("No HDL input specified")

    with tempfile.TemporaryDirectory() as d:
        if build_dir is not None:
            d = build_dir
            os.makedirs(build_dir, exist_ok=True)

        if module is not None:
            verilog_name = os.path.join(d, f'amaranth_output.v')
            verilog_data = verilog.convert(
                elaboratable = module,
                name = module_name,
                ports = open_ports(ports),
                strip_internal_attrs = True,
                platform = platform,
                emit_src=False,
            )
            with open(verilog_name, 'w') as f:
                f.write(verilog_data)
            verilog_sources.append(verilog_name)

        for name, content in extra_sources.items():
            new_path = os.path.join(d, name)
            if os.path.isfile(new_path):
                raise RuntimeError(f"Name collision for file: {name}")
            with open(new_path, 'wb') as f:
                f.write(content)

            if os.path.splitext()[-1] in ['.vhd', '.vhdl']:
                vhdl_sources.append(new_path)
            else:
                verilog_sources.append(new_path)

        if waveform_file is not None and vcd_file is not None:
            raise ValueError("Both waveform_file and vcd_file can't be used at the same time")

        if waveform_file is None:
            waveform_file = vcd_file

        if simulator in simulators:
            Sim = simulators[simulator]
        else:
            warnings.warn(f"Using unknown simulator: {simulator}", stacklevel=2)
            Sim = Simulator

        sim = Sim(
            hdl_toplevel        = toplevel,
            caller_file         = caller_file,
            verilog_sources     = verilog_sources,
            vhdl_sources        = vhdl_sources,
            parameters          = parameters,
            extra_env           = extra_env,
            waveform_file       = waveform_file,
            random_seed         = random_seed,
            directory           = d,
            timescale           = timescale,
        )
        sim.name = simulator

        sim.build_and_run()
