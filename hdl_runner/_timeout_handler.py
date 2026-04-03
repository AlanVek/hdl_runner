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
_SHUTDOWN_REQUESTED = False
_SHUTDOWN_MESSAGE = None


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


def _is_test_active():
    regression_manager = getattr(cocotb, "_regression_manager", None)
    if regression_manager is None:
        return False

    running_test = getattr(regression_manager, "_running_test", None)
    if running_test is None:
        return False

    return getattr(running_test, "_outcome", None) is None


def _frame_has_local(frame, local_name):
    while frame is not None:
        if frame.f_locals.get(local_name, False):
            return True
        frame = frame.f_back
    return False


def _mark_regression_shutdown():
    regression_manager = getattr(cocotb, "_regression_manager", None)
    if regression_manager is None:
        return

    if getattr(regression_manager, "_sim_failure", None) is None:
        regression_manager._sim_failure = _ShutdownOutcome(_get_shutdown_message())


def _request_shutdown(signum, frame):
    global _SHUTDOWN_REQUESTED, _SHUTDOWN_MESSAGE

    if _SHUTDOWN_REQUESTED:
        return

    _SHUTDOWN_MESSAGE = _signal_to_message(signum)
    _mark_regression_shutdown()

    _SHUTDOWN_REQUESTED = True


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
    def _timeout_trace(frame, event, arg):
        if (
            _SHUTDOWN_REQUESTED
            and _is_test_active()
            and _frame_has_local(frame, "_hdl_runner_in_wrapped_test")
        ):
            raise SimTimeoutError(_get_shutdown_message())
        return _timeout_trace

    @functools.wraps(original_func)
    async def wrapper(dut):
        _hdl_runner_in_wrapped_test = True

        if _SHUTDOWN_REQUESTED:
            _mark_regression_shutdown()
            raise SimTimeoutError(_get_shutdown_message())

        previous_trace = sys.gettrace()
        sys.settrace(_timeout_trace)

        try:
            await original_func(dut)
        finally:
            sys.settrace(previous_trace)

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
