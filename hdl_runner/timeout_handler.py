import functools
import importlib
import os
import signal
import time
from importlib.metadata import version

import cocotb
from packaging.version import Version

COCOTB_2_0_0 = Version(version("cocotb")) >= Version("2.0.0")

if COCOTB_2_0_0:
    from cocotb._decorators import Parameterized, Test
    from cocotb.triggers import SimTimeoutError, Timer
else:
    from cocotb.decorators import test as Test
    from cocotb.result import SimTimeoutError
    from cocotb.triggers import Timer

_DEADLINE = os.environ.get("HDL_RUNNER_TIMEOUT_DEADLINE")
if _DEADLINE is not None:
    _DEADLINE = float(_DEADLINE)

_USER_MODULE = os.environ["HDL_RUNNER_TEST_MODULE"]
_HAS_DEADLINE_SIGNAL = False
_TIMEOUT_EXPIRED = _DEADLINE is not None and time.monotonic() >= _DEADLINE
_USE_POLLING_FALLBACK = False


def _restore_default_handler(signum):
    try:
        signal.signal(signum, signal.SIG_DFL)
    except (AttributeError, OSError, ValueError):
        pass


def _signal_to_message(signum):
    if signum in {
        getattr(signal, "SIGINT", None),
        getattr(signal, "SIGUSR2", None),
    }:
        return "hdl_runner interrupted by ctrl+C"
    return "hdl_runner timeout expired"


def _raise_shutdown(signum):
    _restore_default_handler(signum)
    raise SimTimeoutError(_signal_to_message(signum))


def _install_signal_handler(signum):
    if signum is None:
        return False

    try:
        signal.signal(signum, lambda _signum, _frame: _raise_shutdown(_signum))
    except (AttributeError, OSError, ValueError):
        return False
    return True


def _should_shutdown():
    global _TIMEOUT_EXPIRED

    if _TIMEOUT_EXPIRED:
        return True

    if _DEADLINE is None or not _USE_POLLING_FALLBACK:
        return False

    if time.monotonic() >= _DEADLINE:
        _TIMEOUT_EXPIRED = True
        return True

    return False


def _configure_timeout_signal():
    global _HAS_DEADLINE_SIGNAL, _TIMEOUT_EXPIRED, _USE_POLLING_FALLBACK

    if _DEADLINE is None or _TIMEOUT_EXPIRED:
        return

    remaining = _DEADLINE - time.monotonic()
    if remaining <= 0:
        _TIMEOUT_EXPIRED = True
        return

    if not hasattr(signal, "setitimer") or not hasattr(signal, "ITIMER_REAL"):
        _USE_POLLING_FALLBACK = True
        return

    timeout_signal = getattr(signal, "SIGALRM", None)
    if timeout_signal is None or not _install_signal_handler(timeout_signal):
        _USE_POLLING_FALLBACK = True
        return

    signal.setitimer(signal.ITIMER_REAL, remaining)
    _HAS_DEADLINE_SIGNAL = True


for _shutdown_signal in (
    getattr(signal, "SIGINT", None),
    getattr(signal, "SIGUSR1", None),
    getattr(signal, "SIGUSR2", None),
):
    _install_signal_handler(_shutdown_signal)

if _DEADLINE is not None and not hasattr(signal, "setitimer"):
    _USE_POLLING_FALLBACK = _DEADLINE is not None

_configure_timeout_signal()


def _wrap_func(original_func):
    @functools.wraps(original_func)
    async def wrapper(dut):
        if _should_shutdown():
            _raise_shutdown(getattr(signal, "SIGALRM", signal.SIGINT))

        if _USE_POLLING_FALLBACK and not _HAS_DEADLINE_SIGNAL:
            async def _watchdog():
                while True:
                    await Timer(1, "us")
                    if _should_shutdown():
                        _raise_shutdown(getattr(signal, "SIGALRM", signal.SIGINT))

            cocotb.start_soon(_watchdog())

        await original_func(dut)

    return wrapper


_mod = importlib.import_module(_USER_MODULE)

if COCOTB_2_0_0:
    for _name, _obj in list(vars(_mod).items()):
        if isinstance(_obj, Test):
            globals()[_name] = Test(
                func=_wrap_func(_obj.func),
                name=_obj.name,
                module=_obj.module,
                doc=_obj.doc,
                timeout_time=_obj.timeout_time,
                timeout_unit=_obj.timeout_unit,
                expect_fail=_obj.expect_fail,
                expect_error=_obj.expect_error,
                skip=_obj.skip,
                stage=_obj.stage,
            )
        elif isinstance(_obj, Parameterized):
            _obj.test_template = Test(
                func=_wrap_func(_obj.test_template.func),
                name=_obj.test_template.name,
                module=_obj.test_template.module,
                doc=_obj.test_template.doc,
                timeout_time=_obj.test_template.timeout_time,
                timeout_unit=_obj.test_template.timeout_unit,
                expect_fail=_obj.test_template.expect_fail,
                expect_error=_obj.test_template.expect_error,
                skip=_obj.test_template.skip,
                stage=_obj.test_template.stage,
            )
            globals()[_name] = _obj
    try:
        del _name, _obj
    except NameError:
        pass
else:
    for _name, _obj in list(vars(_mod).items()):
        if isinstance(_obj, Test):
            globals()[_name] = cocotb.test(
                timeout_time=_obj.timeout_time,
                timeout_unit=_obj.timeout_unit,
                expect_fail=_obj.expect_fail,
                expect_error=_obj.expect_error,
                skip=_obj.skip,
                stage=_obj.stage,
            )(_wrap_func(_obj._func))
    try:
        del _name, _obj
    except NameError:
        pass
