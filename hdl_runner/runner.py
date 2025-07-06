import os
import tempfile
import shutil
import inspect
import warnings
from amaranth.back import verilog
import find_libpython
import sys
import cocotb

with warnings.catch_warnings():
    warnings.filterwarnings("ignore")
    from cocotb.runner import get_runner

def open_ports(ports):
    from amaranth import Record, Signal
    from amaranth.hdl.ast import SignalDict, SignalKey

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

def _set_env_workaround(simulator, caller_file):
    def _set_env(self):
        for e in os.environ:
            self.env[e] = os.environ[e]

        if "LIBPYTHON_LOC" not in self.env:
            libpython_path = find_libpython.find_libpython()
            if not libpython_path:
                raise ValueError(
                    "Unable to find libpython, please make sure the appropriate libpython is installed"
                )
            self.env["LIBPYTHON_LOC"] = libpython_path

        self.env["PATH"] += os.pathsep + cocotb.config.libs_dir
        self.env["PYTHONPATH"] = os.pathsep.join(sys.path + [os.path.dirname(caller_file)])
        # self.env["PYTHONHOME"] = sys.base_prefix
        self.env["TOPLEVEL"] = self.sim_hdl_toplevel
        self.env["MODULE"] = self.test_module

    simulator._set_env = _set_env.__get__(simulator)

def run(
    module          = None,
    ports           = None,
    waveform_file   = None,
    verilog_sources = None,
    vhdl_sources    = None,
    toplevel        = 'top',
    simulator       = 'icarus',
    random_seed     = None,
    extra_env       = None,
    build_dir       = None,
    parameters      = None,
    platform        = None,
    vcd_file        = None, # For backwards compatibility
    timescale       = ('1ns', '1ps'),
):
    caller_file = os.path.abspath(inspect.stack()[1].filename)
    test_module = os.path.splitext(os.path.basename(caller_file))[0]

    if ports is None:
        ports = []

    if verilog_sources is None:
        verilog_sources = []

    if vhdl_sources is None:
        vhdl_sources = []

    if extra_env is None:
        extra_env = {}

    if parameters is None:
        parameters = {}

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
            common_args = {
                'elaboratable': module,
                'name': toplevel,
                'ports': open_ports(ports),
                'strip_internal_attrs': True,
            }
            if platform is None:
                verilog_data = verilog.convert(**common_args, emit_src=False)
            else:
                verilog_data = platform.convert_to_verilog(**common_args)
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

        build_args  = []
        test_args   = []
        plusargs    = []

        wave_name   = None
        fst         = False

        if simulator == 'verilator':
            build_args.append('--Wno-fatal')
        elif simulator == 'icarus':
            # Workaround for uninitialized registers
            build_args.append('-g2005')

        if waveform_file is not None and vcd_file is not None:
            raise ValueError("Both waveform_file and vcd_file can't be used at the same time")

        if waveform_file is None:
            waveform_file = vcd_file

        if waveform_file is not None:
            extension = os.path.splitext(waveform_file)[-1]
            if extension == '.fst':
                fst = True
            elif extension != '.vcd':
                raise ValueError(f"Invalid extension for waveform: {extension}. Supported extensions are .vcd and .fst")

            if simulator == 'verilator':
                extra_args = ['--trace-structs']
                if fst:
                    wave_name = 'dump.fst'
                    extra_args.append('--trace-fst')
                else:
                    wave_name = 'dump.vcd'
                build_args.extend(extra_args)
                test_args.extend(extra_args)

            elif simulator == 'icarus':
                wave_name = f'{toplevel}.fst'
                if not fst:
                    plusargs.append('-vcd')

        waves = wave_name is not None

        runner = get_runner(simulator)
        runner.build(
            verilog_sources = verilog_sources,
            vhdl_sources    = vhdl_sources,
            hdl_toplevel    = toplevel,
            waves           = waves,
            timescale       = timescale,
            build_dir       = d,
            build_args      = build_args,
            parameters      = parameters,
        )

        # Workaround for Icarus to export VCD
        if simulator == 'icarus' and not fst:
            waves = False

        err_msg = None
        try:
            _set_env_workaround(runner, caller_file)
            runner.test(
                hdl_toplevel    = toplevel,
                test_module     = test_module,
                timescale       = timescale,
                waves           = waves,
                build_dir       = d,
                test_dir        = d,
                test_args       = test_args,
                plusargs        = plusargs,
                seed            = random_seed,
                extra_env       = extra_env,
            )
        except BaseException as e:
            err_msg = str(e)

        if wave_name is not None:
            wave = os.path.join(d, wave_name)
            if os.path.isfile(wave):
                shutil.copy2(wave, waveform_file)
            else:
                warnings.warn(f"Failed to find waveform output file: {wave}", stacklevel=2)

        if err_msg is not None:
            raise RuntimeError(f"Test failed: {err_msg}")
