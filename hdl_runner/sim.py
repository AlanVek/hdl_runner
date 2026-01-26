import os
import shutil
import warnings
import find_libpython
import sys
import cocotb
from importlib.metadata import version
from packaging.version import Version
import subprocess

COCOTB_2_0_0 = Version(version("cocotb")) >= Version("2.0.0")

if COCOTB_2_0_0:
    import cocotb_tools
    from cocotb_tools.runner import get_runner, _as_sv_literal, _shlex_join
else:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        from cocotb.runner import get_runner, shlex_join

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
        timeout: float = None,
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
        self.timeout            = timeout

        self.test_module        = caller_file
        self.wave_name          = None
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
            pythonpath = sys.path
            if self.pythonpath is not None:
                pythonpath = pythonpath + [self.pythonpath]
            runner.env["PYTHONPATH"] = os.pathsep.join(pythonpath)
            if COCOTB_2_0_0:
                runner.env["PYGPI_PYTHON_BIN"] = sys.executable
            # runner.env["PYTHONHOME"] = sys.base_prefix
            runner.env[("COCOTB_" if COCOTB_2_0_0 else "") + "TOPLEVEL"] = runner.sim_hdl_toplevel
            runner.env["COCOTB_TEST_MODULES" if COCOTB_2_0_0 else "MODULE"] = runner.test_module

        self.runner._set_env = _set_env.__get__(self.runner)

    def _execute_cmds_workaround(self):
        def _execute_cmds(runner, cmds, cwd, stdout = None):
            __tracebackhide__ = True  # Hide the traceback when using PyTest.

            for cmd in cmds:
                if COCOTB_2_0_0:
                    runner.log.info("Running command %s in directory %s", _shlex_join(cmd), cwd)
                else:
                    print(f"INFO: Running command {shlex_join(cmd)} in directory {cwd}")

                kwargs = {}
                if COCOTB_2_0_0:
                    kwargs['check'] = True

                # TODO: create a thread to handle stderr and log as error?
                # TODO: log forwarding

                stderr = None if stdout is None else subprocess.STDOUT
                process = subprocess.run(
                    cmd, cwd=cwd, env=runner.env, stdout=stdout, stderr=stderr, timeout=self.timeout, **kwargs
                )

                if not COCOTB_2_0_0:
                    if process.returncode != 0:
                        raise SystemExit(
                            f"Process {process.args[0]!r} terminated with error {process.returncode}"
                        )

        self.runner._execute_cmds = _execute_cmds.__get__(self.runner)

    def _pre_build(self):
        """
        Prepare the simulator runner and environment before building.
        """
        self.runner = get_runner(self.name)
        self._set_env_workaround()
        self._execute_cmds_workaround()

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
            if os.path.isfile(self.wave_name):
                try:
                    shutil.copy2(self.wave_name, self.waveform_file)
                except shutil.SameFileError:
                    pass
            else:
                warnings.warn(f"Failed to find waveform output file: {self.wave_name}", stacklevel=2)

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
            if self.has_waves:
                dumpfile_path = os.path.abspath(self.waveform_file)
            else:
                dumpfile_path = runner.build_dir / f"{runner.hdl_toplevel}.fst"

            if COCOTB_2_0_0:
                dumpfile_path = _as_sv_literal(str(dumpfile_path))
            else:
                dumpfile_path = f'"{dumpfile_path}"'

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
        self._create_iverilog_dump_file_workaround()

        # Workaround for uninitialized registers
        self.build_args.append('-g2005')

        if self.has_waves:
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
            self.wave_name = os.path.join(self.directory, f'dump.{self.waveform_format}')
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

        if self.has_waves:
            if self.waveform_format != 'fst':
                raise RuntimeError(f"NVC doesn't support .{self.waveform_format} waveform, only .fst")
            self.plusargs.append(f'--wave={os.path.abspath(self.waveform_file)}')

        self.plusargs.append(f'--dump-arrays')
        self.build_args.append('--std=2008')

        # TODO: Allowed memory, may need to be tweaked
        self.build_args.append('-M 256m')