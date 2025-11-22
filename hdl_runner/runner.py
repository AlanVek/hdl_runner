import os
import tempfile
import inspect
import warnings
from amaranth.build.plat import Platform as AmaranthPlatform
from celosia import Platform as CelosiaPlatform
import sys
import hdl_runner.sim
from hdl_runner.sim import Simulator
from hdl_runner.utils import get_lang_map, open_ports, convert_platform
from typing import Union

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
        backend: str = None,
    ):
        self.module = module
        self.lang = lang
        self.simulator = simulator
        self.module_name = module_name
        self.ports = ports
        self.backend = backend

        self.lang_map = get_lang_map(backend)
        self.hdl_sources: dict[str, list[str]] = {}
        self.extra_sources: dict[str] = {}
        self.Sim: type[Simulator] = None
        self.langs = set()
        self.directory: str = None

        self._get_simulator_and_langs()

    def _get_simulator_and_langs(self):
        self.langs.clear()

        _simulators = [
            SimClass for SimClass in hdl_runner.sim.__dict__.values() if isinstance(SimClass, type) and issubclass(SimClass, Simulator)
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

    def _process_extra_sources(self, platform: Union[AmaranthPlatform, CelosiaPlatform]):
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

    def convert_amaranth(self, platform: Union[AmaranthPlatform, CelosiaPlatform]):
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
            platform = convert_platform(platform, self.backend)
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

    @classmethod
    def resolve_caller(cls, caller: str = None) -> tuple[str, str]:
        if caller is None:
            caller = os.path.abspath(inspect.stack()[2].filename)

        if '/' in caller or '\\' in caller or caller.endswith('.py'):
            if not os.path.isabs(caller) or os.path.splitext(caller)[1] not in ('', '.py'):
                raise ValueError(f"Caller file must be an absolute path, not {caller}")
            caller_file, pythonpath = cls._full_module_path_from_file(caller)
        else:
            caller_file = caller
            pythonpath = None

        return caller_file, pythonpath

    @classmethod
    def _full_module_path_from_file(cls, path: str) -> tuple[str, str]:
        dir_path = os.path.dirname(os.path.abspath(path))
        filename = os.path.splitext(os.path.basename(path))[0]
        module = []

        for p in sys.path:
            abs_sys_path = os.path.join(os.path.abspath(p), '')
            if not dir_path.startswith(abs_sys_path):
                continue

            rel_dir_path = dir_path.split(abs_sys_path, maxsplit=1)[1]
            for directory in rel_dir_path.split(os.sep):
                next_dir = os.path.join(abs_sys_path, directory)
                if not os.path.isfile(os.path.join(next_dir, '__init__.py')):
                    break
                module.append(directory)
                abs_sys_path = next_dir
            else:
                break

            module.clear()

        if module:
            module.append(filename)
            return '.'.join(module), None

        return filename, dir_path

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
    backend: str = None,
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
        backend: string with backend name (e.g. amaranth, celosia)
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
        ports = [] if ports is None else ports,
        backend = backend,
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

        caller_file, pythonpath = runner.resolve_caller(caller_file)

        sim = runner.Sim(
            hdl_toplevel        = toplevel,
            caller_file         = caller_file,
            pythonpath          = pythonpath,
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
