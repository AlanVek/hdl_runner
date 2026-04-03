import functools
import importlib
import os
import signal
import sys
from importlib.metadata import version

import cocotb
from packaging.version import Version
from cocotb.task import Task as CocotbTask

COCOTB_2_0_0 = Version(version("cocotb")) >= Version("2.0.0")

from cocotb.regression import RegressionManager
if COCOTB_2_0_0:
    from cocotb._decorators import Parameterized, Test
    from cocotb._outcomes import Error as OutcomeError
    from cocotb.triggers import SimTimeoutError
else:
    from cocotb.decorators import test as Test
    from cocotb.outcomes import Error as OutcomeError
    from cocotb.result import SimTimeoutError

_USER_MODULE = os.environ["HDL_RUNNER_TEST_MODULE"]
_SHUTDOWN_REQUESTED = False
_SHUTDOWN_MESSAGE = None
_TRACE_INSTALLED = False
_ABORT_TRACE_INSTALLED = False
_ABORT_PENDING = False


def _signal_to_message(signum):
    if signum in {
        getattr(signal, "SIGINT", None),
        getattr(signal, "SIGUSR2", None),
    }:
        return "hdl_runner interrupted by ctrl+C"
    return "hdl_runner timeout expired"


def _get_shutdown_message():
    return _SHUTDOWN_MESSAGE or "hdl_runner timeout expired"


def _get_regression_manager():
    return getattr(
        cocotb,
        "_regression_manager" if COCOTB_2_0_0 else "regression_manager",
        None,
    )


def _get_scheduler():
    return getattr(cocotb, "_scheduler_inst" if COCOTB_2_0_0 else "scheduler", None)


def _frame_in_wrapped_test(frame):
    while frame is not None:
        if frame.f_locals.get("_hdl_runner_timeout_wrapper", False):
            return True
        frame = frame.f_back
    return False


def _get_main_test_task():
    regression_manager = _get_regression_manager()
    if regression_manager is None:
        return None

    if COCOTB_2_0_0:
        running_test = getattr(regression_manager, "_running_test", None)
        if running_test is None:
            return None
        return getattr(running_test, "_main_task", None)

    return getattr(regression_manager, "_test_task", None)


def _iter_coro_frames(coro, seen=None):
    if seen is None:
        seen = set()

    while coro is not None and id(coro) not in seen:
        seen.add(id(coro))

        frame = getattr(coro, "cr_frame", None)
        if frame is None:
            frame = getattr(coro, "gi_frame", None)
        if frame is not None:
            yield frame

        next_coro = getattr(coro, "cr_await", None)
        if next_coro is None:
            next_coro = getattr(coro, "gi_yieldfrom", None)
        coro = next_coro


def _timeout_trace(frame, event, arg):
    if _SHUTDOWN_REQUESTED and _frame_in_wrapped_test(frame):
        raise SimTimeoutError(_get_shutdown_message())
    return _timeout_trace


def _abort_trace(frame, event, arg):
    global _ABORT_PENDING

    if _ABORT_PENDING:
        _ABORT_PENDING = False
        _abort_running_test()

    return _abort_trace


def _install_trace_on_task(task, seen_coros):
    coro = getattr(task, "_coro", None)
    if coro is None:
        return False

    installed = False
    for task_frame in _iter_coro_frames(coro, seen_coros):
        task_frame.f_trace = _timeout_trace
        installed = True

        for value in task_frame.f_locals.values():
            if isinstance(value, CocotbTask):
                installed = _install_trace_on_task(value, seen_coros) or installed

    return installed


def _enable_timeout_trace(frame):
    global _TRACE_INSTALLED

    if not _TRACE_INSTALLED:
        sys.settrace(_timeout_trace)
        _TRACE_INSTALLED = True

    test_task = _get_main_test_task()
    if test_task is not None:
        installed = _install_trace_on_task(test_task, set())
        if installed:
            return

    while frame is not None:
        frame.f_trace = _timeout_trace
        frame = frame.f_back


def _enable_abort_trace(frame):
    global _ABORT_TRACE_INSTALLED, _ABORT_PENDING

    if not _ABORT_TRACE_INSTALLED:
        sys.settrace(_abort_trace)
        _ABORT_TRACE_INSTALLED = True

    _ABORT_PENDING = True

    while frame is not None:
        frame.f_trace = _abort_trace
        frame = frame.f_back


def _has_active_test():
    regression_manager = _get_regression_manager()
    if regression_manager is None:
        return False

    if COCOTB_2_0_0:
        running_test = getattr(regression_manager, "_running_test", None)
        return running_test is not None and getattr(running_test, "_outcome", None) is None
    else:
        test_task = getattr(regression_manager, "_test_task", None)
        if test_task is None:
            return False
        done = getattr(test_task, "done", None)
        return not callable(done) or not done()


def _abort_running_test():
    regression_manager = _get_regression_manager()
    if regression_manager is None:
        return

    if COCOTB_2_0_0:
        running_test = getattr(regression_manager, "_running_test", None)
        if running_test is not None and getattr(running_test, "_outcome", None) is None:
            running_test.abort(OutcomeError(SimTimeoutError(_get_shutdown_message())))
    else:
        scheduler = _get_scheduler()
        if scheduler is not None and getattr(regression_manager, "_test_task", None) is not None:
            scheduler._finish_test(SimTimeoutError(_get_shutdown_message()))


def _record_remaining_timeout_failures(regression_manager):
    while True:
        test = regression_manager._next_test()
        if test is None:
            return regression_manager._tear_down()
        regression_manager._record_result(
            test=test,
            outcome=OutcomeError(SimTimeoutError(_get_shutdown_message())),
            wall_time_s=0,
            sim_time_ns=0,
        )


_original_execute = RegressionManager._execute


def _patched_execute(self):
    if not _SHUTDOWN_REQUESTED:
        return _original_execute(self)

    if COCOTB_2_0_0:
        if getattr(self, "_sim_failure", None) is None:
            self._sim_failure = OutcomeError(SimTimeoutError(_get_shutdown_message()))
        return _original_execute(self)
    else:
        return _record_remaining_timeout_failures(self)

RegressionManager._execute = _patched_execute


def _request_shutdown(signum, frame):
    global _SHUTDOWN_REQUESTED, _SHUTDOWN_MESSAGE

    if not _SHUTDOWN_REQUESTED:
        _SHUTDOWN_MESSAGE = _signal_to_message(signum)
        _SHUTDOWN_REQUESTED = True

    if frame is not None and _frame_in_wrapped_test(frame):
        raise SimTimeoutError(_get_shutdown_message())

    if not _has_active_test():
        raise SimTimeoutError(_get_shutdown_message())

    if frame is None:
        _abort_running_test()
    elif COCOTB_2_0_0:
        _enable_timeout_trace(frame)
    else:
        _enable_abort_trace(frame)

def _install_signal_handler(signum):
    if signum is None:
        return

    try:
        signal.signal(signum, lambda _signum, _frame: _request_shutdown(_signum, _frame))
    except (AttributeError, OSError, ValueError):
        return


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
        _hdl_runner_timeout_wrapper = True

        if _SHUTDOWN_REQUESTED:
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
