import os
import tempfile
import shutil
import inspect
import warnings
from amaranth.back import verilog
from amaranth.build.plat import Platform
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

    if isinstance(ports, (int, str, float)):
        raise ValueError(f"Invalid port: {ports}")

    if not isinstance(ports, Record) and hasattr(ports, 'as_value') and callable(ports.as_value):
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
    langs = ()

    def __init__(
        self,
        hdl_toplevel: str,
        caller_file: str,
        hdl_sources: dict[str, list[str]],
        parameters: dict = None,
        extra_env: dict = None,
        waveform_file: str = None,
        random_seed: int = None,
        directory: str = '.',
        timescale: tuple = ('1ns', '1ps'),
        extra_args: list[str] = None,
    ):
        """
        Args:
            hdl_toplevel: Name of the top-level module/entity.
            caller_file: Path to the Python file invoking the runner.
            hdl_sources: Dictionary of HDL type and source files.
            parameters: Dictionary of parameters to pass to the design.
            extra_env: Extra environment variables for the simulator.
            waveform_file: Output file for simulation waveforms.
            random_seed: Seed for simulation randomness.
            directory: Build directory.
            timescale: HDL timescale as a tuple (e.g., ('1ns', '1ps')).
        """
        if extra_env is None:
            extra_env = {}

        if parameters is None:
            parameters = {}

        self.hdl_toplevel       = hdl_toplevel
        self.caller_file        = caller_file
        self.hdl_sources        = hdl_sources
        self.parameters         = parameters
        self.extra_env          = extra_env
        self.waveform_file      = waveform_file
        self.random_seed        = random_seed
        self.directory          = directory
        self.timescale          = timescale

        self.test_module        = os.path.splitext(os.path.basename(caller_file))[0]
        self.wave_name          = waveform_file
        self.has_waves          = waveform_file is not None
        self.build_args         = extra_args or []
        self.test_args          = []
        self.plusargs           = []
        self.waveform_format    = None

        if not isinstance(self.build_args, list):
            raise ValueError(f"Invalid extra_args: {extra_args}")

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
            **self.hdl_sources,
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
    langs = ('verilog',)

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
    langs = ('verilog',)

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
    langs = ('vhdl',)

    def _pre_build(self):
        """
        Prepare GHDL-specific build arguments and waveform handling.
        """
        super()._pre_build()
        self.hdl_toplevel = self.hdl_toplevel.lower()
        self.wave_name = None

        if self.has_waves:
            self.plusargs.append(f'--{self.waveform_format}={os.path.abspath(self.waveform_file)}')

        self.build_args.append('--std=08')

    def _pre_run(self):
        """
        Prepare GHDL-specific test arguments
        """
        super()._pre_run()
        self.test_args.append('--std=08')

class Nvc(Simulator):
    """
    NVC simulator integration.
    """
    langs = ('vhdl',)

    def _pre_build(self):
        """
        Prepare NVC-specific build arguments and waveform handling.
        """
        super()._pre_build()
        self.hdl_toplevel = self.hdl_toplevel.lower()
        self.wave_name = None

        if self.has_waves:
            if self.waveform_format != 'fst':
                raise RuntimeError(f"NVC doesn't support .{self.waveform_format} waveform, only .fst")
            self.plusargs.append(f'--wave={os.path.abspath(self.waveform_file)}')

        self.plusargs.append(f'--dump-arrays')
        self.build_args.append('--std=2008')

        # TODO: Allowed memory, may need to be tweaked
        self.build_args.append('-M 256m')

def get_lang_map():
    """
    Returns a mapping of HDL language names to converter classes.
    """
    class VerilogConverter:
        extensions = ('v',)
        default_extension = 'v'

        def convert(self, *args, **kwargs):
            return verilog.convert(*args, **kwargs)

    class VHDLConverter:
        extensions = ('vhd', 'vhdl')
        default_extension = 'vhd'

        def convert(self, *args, **kwargs):
            raise NotImplementedError("Amaranth to VHDL not supported")

    return {
        'verilog': VerilogConverter,
        'vhdl': VHDLConverter,
    }

class _RunnerHelper:
    """
    Helper class for managing simulation setup, HDL sources, and conversion.
    """
    def __init__(
        self,
        module = None,
        lang: str = None,
        simulator: str = None,
        module_name: str = None,
        ports: list = None,
    ):
        self.module = module
        self.lang = lang
        self.simulator = simulator
        self.module_name = module_name
        self.ports = ports

        self.lang_map = get_lang_map()
        self.hdl_sources: dict[str, list[str]] = {}
        self.extra_sources: dict[str] = {}
        self.Sim: type[Simulator] = None
        self.langs = set()
        self.directory: str = None

        self._get_simulator_and_langs()

    def _get_simulator_and_langs(self):
        self.langs.clear()

        _simulators = [
            SimClass for SimClass in globals().values() if isinstance(SimClass, type) and issubclass(SimClass, Simulator)
        ]
        simulators = {sim.__name__.lower(): sim for sim in _simulators if sim is not Simulator}

        if self.simulator in simulators:
            self.Sim = simulators[self.simulator]
            if self.module is not None and self.lang is not None and self.lang.lower() not in self.Sim.langs:
                raise ValueError(f"Simulator {self.simulator} only supports {' or '.join(self.Sim.langs) if self.Sim.langs else 'no lang'}, can't use requested lang {self.lang}")
            self.langs.update(map(str.lower, self.Sim.langs))

        else:
            if self.module is not None and self.lang is None:
                raise RuntimeError(f"'lang' must be provided when using unknown simulator ({self.simulator})")

            warnings.warn(f"Using unknown simulator: {self.simulator}", stacklevel=2)
            self.langs.update((self.lang.lower(), *self.lang_map.keys()))
            self.Sim = Simulator

    def _process_extra_sources(self, platform: Platform):
        if platform is None:
            return

        self.extra_sources.clear()
        for name, content in platform.extra_files.items():
            if isinstance(content, str):
                content = content.encode('utf-8')
            elif not isinstance(content, bytes):
                raise ValueError(f"Invalid extra file type: {type(content)}")
            self.extra_sources[name] = content

            new_path = os.path.join(self.directory, name)
            if os.path.isfile(new_path):
                raise RuntimeError(f"Name collision for file: {name}")

            with open(new_path, 'wb') as f:
                f.write(content)

            extension = os.path.splitext(name)[-1]
            for key, hdl in self.lang_map.items():
                if extension[1:] not in hdl.extensions or key not in self.langs:
                    continue
                self.hdl_sources[key].append(new_path)
                break
            else:
                raise RuntimeError(f"Failed to find language for simulator {self.simulator} that supports file {name}")

    def set_working_directory(self, directory: str):
        """
        Sets the working directory for build artifacts.

        Args:
            directory (str): Directory path.
        """
        self.directory = directory

    def convert_amaranth(self, platform: Platform):
        """
        Converts the Amaranth module to HDL and adds it to sources.

        Args:
            platform (Platform): Optional Amaranth platform for conversion.
        """
        if self.directory is None:
            self.set_working_directory(os.getcwd())

        self._process_extra_sources(platform)

        if self.module is None:
            return

        for new_lang in self.langs:
            if new_lang in self.lang_map:
                lang = new_lang
                break
        else:
            raise ValueError(f"Failed to select HDL language for Amaranth output from options: {', '.join(self.langs)}")

        converter = self.lang_map[lang]()
        filename = os.path.join(self.directory, f'amaranth_output.{converter.default_extension}')
        hdl_data = converter.convert(
            self.module,
            name = self.module_name,
            ports = open_ports(self.ports),
            platform = platform,
        )
        with open(filename, 'w') as f:
            f.write(hdl_data)

        self.hdl_sources[lang].append(filename)

    def set_hdl_sources(self, **kwargs):
        """
        Sets HDL sources for simulation.

        Args:
            kwargs: Keyword arguments mapping language to list of source files.
        """
        self.hdl_sources.clear()

        for key, new_sources in kwargs.items():
            if new_sources is None:
                new_sources = []

            if new_sources and key not in self.langs:
                raise ValueError(f"Simulator {self.simulator} doesn't support {key} sources")

            if not isinstance(new_sources, (list, tuple, set)):
                raise ValueError(f"Invalid value for {key}_sources: {new_sources}")

            self.hdl_sources[key] = list(new_sources)

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
    lang: str = None,
    caller_file: str = None,
    extra_args: list = None,
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
        simulator: Simulator backend to use ('icarus', 'verilator', 'ghdl', 'nvc').
        random_seed: Seed for simulation randomness.
        extra_env: Extra environment variables for the simulator.
        build_dir: Directory for build artifacts (default: temporary).
        parameters: Dictionary of parameters to pass to the design.
        platform: Optional Amaranth platform for conversion.
        vcd_file: Deprecated, use waveform_file instead.
        timescale: HDL timescale as a tuple.
        lang: HDL language to be used (mostly just required for unknown simulator)
        caller_file: Path to python file with the testbench. Default is the file calling run().
        extra_args: list with extra compilation arguments
    """

    if toplevel is None:
        toplevel = module_name = 'top'
        if module is None:
            raise ValueError("Top-level name must be provided if no Amaranth module is given")
    else:
        module_name = toplevel

    runner = _RunnerHelper(
        module = module,
        lang = lang,
        simulator = simulator,
        module_name = module_name,
        ports = ports or [],
    )

    runner.set_hdl_sources(**{
        key.rsplit('_sources', maxsplit=1)[0]: value for key, value in locals().items() if key.endswith('_sources')
    })

    with tempfile.TemporaryDirectory() as d:
        if build_dir is not None:
            d = build_dir
            os.makedirs(build_dir, exist_ok=True)

        runner.set_working_directory(str(d))
        runner.convert_amaranth(platform)

        if not any(runner.hdl_sources.values()):
            raise ValueError("No HDL input specified")

        if waveform_file is not None and vcd_file is not None:
            raise ValueError("Both waveform_file and vcd_file can't be used at the same time")

        if waveform_file is None:
            waveform_file = vcd_file

        if caller_file is None:
            caller_file = os.path.abspath(inspect.stack()[1].filename)

        sim = runner.Sim(
            hdl_toplevel        = toplevel,
            caller_file         = caller_file,
            parameters          = parameters,
            extra_env           = extra_env,
            waveform_file       = waveform_file,
            random_seed         = random_seed,
            directory           = d,
            timescale           = timescale,
            hdl_sources         = {f'{key}_sources': value for key, value in runner.hdl_sources.items()},
            extra_args          = extra_args,
        )
        sim.name = simulator

        sim.build_and_run()
