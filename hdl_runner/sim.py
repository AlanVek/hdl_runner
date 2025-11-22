import os
import shutil
import warnings
import find_libpython
import sys
import cocotb
from importlib.metadata import version
from packaging.version import Version

COCOTB_2_0_0 = Version(version("cocotb")) >= Version("2.0.0")

if COCOTB_2_0_0:
    import cocotb_tools
    from cocotb_tools.runner import get_runner, _as_sv_literal
else:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        from cocotb.runner import get_runner

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
        pythonpath: str = None,
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
            pythonpath: Python path to add include directories.
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
        self.pythonpath         = pythonpath
        self.parameters         = parameters
        self.extra_env          = extra_env
        self.waveform_file      = waveform_file
        self.random_seed        = random_seed
        self.directory          = directory
        self.timescale          = timescale

        self.test_module        = caller_file
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

            cocotb_libs = str(cocotb_tools.config.libs_dir if COCOTB_2_0_0 else cocotb.config.libs_dir)

            runner.env["PATH"] += os.pathsep + cocotb_libs
            if self.pythonpath is not None:
                runner.env["PYTHONPATH"] = os.pathsep.join(sys.path + [self.pythonpath])
            if COCOTB_2_0_0:
                runner.env["PYGPI_PYTHON_BIN"] = sys.executable
            # runner.env["PYTHONHOME"] = sys.base_prefix
            runner.env[("COCOTB_" if COCOTB_2_0_0 else "") + "TOPLEVEL"] = runner.sim_hdl_toplevel
            runner.env["COCOTB_TEST_MODULES" if COCOTB_2_0_0 else "MODULE"] = runner.test_module

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
        hdl_sources = self.hdl_sources
        if COCOTB_2_0_0:
            hdl_sources = {'sources': [source for sources in self.hdl_sources.values() for source in sources]}
        self.runner.build(
            **hdl_sources,
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

    def _create_iverilog_dump_file_workaround(self):
        def _create_iverilog_dump_file(runner) -> None:
            dumpfile_path = _as_sv_literal(str(runner.build_dir / f"{runner.hdl_toplevel}.fst"))
            with open(runner.iverilog_dump_file, "w") as f:
                f.write("module cocotb_iverilog_dump();\n")
                f.write("initial begin\n")
                # f.write("    string dumpfile_path;")
                # f.write(
                #     '    if ($value$plusargs("dumpfile_path=%s", dumpfile_path)) begin\n'
                # )
                # f.write("        $dumpfile(dumpfile_path);\n")
                # f.write("    end else begin\n")
                f.write(f"        $dumpfile({dumpfile_path});\n")
                # f.write("    end\n")
                f.write(f"    $dumpvars(0, {runner.hdl_toplevel});\n")
                f.write("end\n")
                f.write("endmodule\n")

        self.runner._create_iverilog_dump_file = _create_iverilog_dump_file.__get__(self.runner)

    def _test_command_workaround(self):
        def _test_command(runner):
            ret = runner.__test_command()
            if isinstance(ret, list) and len(ret) > 0 and isinstance(ret[0], list) and '-none' in ret[0] and '-vcd' in ret[0]:
                ret[0].remove('-none')
            return ret

        self.runner.__test_command = self.runner._test_command
        self.runner._test_command = _test_command.__get__(self.runner)

    def _pre_build(self):
        """
        Prepare Icarus-specific build arguments and waveform handling.
        """
        super()._pre_build()
        if COCOTB_2_0_0:
            self._create_iverilog_dump_file_workaround()

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

        if COCOTB_2_0_0:
            self._test_command_workaround()

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