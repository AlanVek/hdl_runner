import functools
import importlib
import os
import signal
import sys
from importlib.metadata import version

import cocotb
from packaging.version import Version

COCOTB_2_0_0 = Version(version("cocotb")) >= Version("2.0.0")

if COCOTB_2_0_0:
    from cocotb._decorators import Parameterized, Test
    from cocotb.triggers import SimTimeoutError
else:
    from cocotb.decorators import test as Test
    from cocotb.result import SimTimeoutError

_USER_MODULE = os.environ["HDL_RUNNER_TEST_MODULE"]
_USER_PACKAGE = _USER_MODULE.rsplit(".", 1)[0] if "." in _USER_MODULE else None
_SHUTDOWN_REQUESTED = False
_SHUTDOWN_MESSAGE = None
_TRACE_INSTALLED = False


class _ShutdownOutcome:
    def __init__(self, message):
        self._message = message

    def get(self):
        raise SimTimeoutError(self._message)


def _signal_to_message(signum):
    if signum in {
        getattr(signal, "SIGINT", None),
        getattr(signal, "SIGUSR2", None),
    }:
        return "hdl_runner interrupted by ctrl+C"
    return "hdl_runner timeout expired"


def _get_shutdown_message():
    return _SHUTDOWN_MESSAGE or "hdl_runner timeout expired"


def _frame_is_timeout_target(frame):
    if frame.f_locals.get("_hdl_runner_in_wrapped_test", False):
        return True

    module_name = frame.f_globals.get("__name__", "")
    if module_name == _USER_MODULE:
        return True

    return _USER_PACKAGE is not None and module_name.startswith(f"{_USER_PACKAGE}.")


def _stack_has_timeout_target(frame):
    while frame is not None:
        if _frame_is_timeout_target(frame):
            return True
        frame = frame.f_back
    return False


def _timeout_trace(frame, event, arg):
    if _SHUTDOWN_REQUESTED and _stack_has_timeout_target(frame):
        raise SimTimeoutError(_get_shutdown_message())

    return _timeout_trace


def _enable_timeout_trace(frame):
    global _TRACE_INSTALLED

    if not _TRACE_INSTALLED:
        sys.settrace(_timeout_trace)
        _TRACE_INSTALLED = True

    while frame is not None:
        frame.f_trace = _timeout_trace
        frame = frame.f_back


def _mark_regression_shutdown():
    regression_manager = getattr(
        cocotb,
        "_regression_manager" if COCOTB_2_0_0 else "regression_manager",
        None,
    )
    if regression_manager is None:
        return

    if COCOTB_2_0_0:
        if getattr(regression_manager, "_sim_failure", None) is None:
            regression_manager._sim_failure = _ShutdownOutcome(_get_shutdown_message())


def _request_shutdown(signum, frame):
    global _SHUTDOWN_REQUESTED, _SHUTDOWN_MESSAGE

    if not _SHUTDOWN_REQUESTED:
        _SHUTDOWN_MESSAGE = _signal_to_message(signum)
        _SHUTDOWN_REQUESTED = True
        _mark_regression_shutdown()

    if frame is not None and _stack_has_timeout_target(frame):
        raise SimTimeoutError(_get_shutdown_message())

    if frame is not None:
        _enable_timeout_trace(frame)


def _install_signal_handler(signum):
    if signum is None:
        return False

    try:
        signal.signal(signum, lambda _signum, _frame: _request_shutdown(_signum, _frame))
    except (AttributeError, OSError, ValueError):
        return False
    return True

for _shutdown_signal in (
    getattr(signal, "SIGINT", None),
    getattr(signal, "SIGBREAK", None),
    getattr(signal, "SIGUSR1", None),
    getattr(signal, "SIGUSR2", None),
):
    _install_signal_handler(_shutdown_signal)


def _wrap_func(original_func):
    @functools.wraps(original_func)
    async def wrapper(dut):
        _hdl_runner_in_wrapped_test = True

        if _SHUTDOWN_REQUESTED:
            _mark_regression_shutdown()
            raise SimTimeoutError(_get_shutdown_message())

        await original_func(dut)

    return wrapper


_mod = importlib.import_module(_USER_MODULE)

if COCOTB_2_0_0:
    def _wrap_test(test):
        return Test(
            func=_wrap_func(test.func),
            name=test.name,
            module=test.module,
            doc=test.doc,
            timeout_time=test.timeout_time,
            timeout_unit=test.timeout_unit,
            expect_fail=test.expect_fail,
            expect_error=test.expect_error,
            skip=test.skip,
            stage=test.stage,
        )
    for _name, _obj in list(vars(_mod).items()):
        if isinstance(_obj, Test):
            globals()[_name] = _wrap_test(_obj)
        elif isinstance(_obj, Parameterized):
            _obj.test_template = _wrap_test(_obj.test_template)
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
