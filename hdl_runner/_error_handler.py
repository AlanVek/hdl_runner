import functools
import importlib
import os
import signal
import sys
import cocotb
from cocotb.task import Task as CocotbTask

try:
    # Cocotb 2.0.1
    from cocotb._decorators import Parameterized, Test
    from cocotb.triggers import SimTimeoutError
    from cocotb.logging import SimLogFormatter
except ImportError:
    # Cocotb 1.9.2
    from cocotb.decorators import test as Test
    from cocotb.result import SimTimeoutError
    from cocotb.log import SimLogFormatter
    Parameterized = ()

_USER_MODULE = os.getenv("HDL_RUNNER_TEST_MODULE", None)
if _USER_MODULE is None:
    raise RuntimeError("Missing HDL_RUNNER_TEST_MODULE definition")

_SHUTDOWN_REQUESTED = False
_SHUTDOWN_MESSAGE = "hdl_runner timeout expired"
_TRACE_ENABLED = False
_TRACE_FRAME_IDS = set()

_original_format_exception = SimLogFormatter.formatException

def _patched_format_exception(self, exc_info):
    _, exc, _ = exc_info
    if isinstance(exc, SimTimeoutError):
        exc_name = f"{type(exc).__module__}.{type(exc).__qualname__}"
        return exc_name if str(exc) == "" else f"{exc_name}: {exc}"

    return _original_format_exception(self, exc_info)

SimLogFormatter.formatException = _patched_format_exception

def _frame_in_wrapped_test(frame):
    while frame is not None:
        if frame.f_locals.get("_hdl_runner_timeout_wrapper", False):
            return True
        frame = frame.f_back

    return False

def _get_main_test_task():
    regression_manager = getattr(cocotb, "_regression_manager", None) or getattr(cocotb, "regression_manager", None)
    if regression_manager is None:
        return None

    running_test = getattr(regression_manager, "_running_test", None)
    if running_test is not None:
        return getattr(running_test, "_main_task", None)

    return getattr(regression_manager, "_test_task", None)

def _iter_coro_frames(coro):
    seen = set()

    while coro is not None and id(coro) not in seen:
        seen.add(id(coro))

        frame = getattr(coro, "cr_frame", None) or getattr(coro, "gi_frame", None)
        if frame is not None:
            yield frame

        coro = getattr(coro, "cr_await", None) or getattr(coro, "gi_yieldfrom", None)

def _trace_task(task, seen_tasks=None):
    if seen_tasks is None:
        seen_tasks = set()

    if id(task) in seen_tasks:
        return
    seen_tasks.add(id(task))

    coro = getattr(task, "_coro", None)
    if coro is None:
        return

    for frame in _iter_coro_frames(coro):
        _TRACE_FRAME_IDS.add(id(frame))
        frame.f_trace = _timeout_trace

        for value in frame.f_locals.values():
            if isinstance(value, CocotbTask):
                _trace_task(value, seen_tasks)

def _enable_timeout_trace():
    global _TRACE_ENABLED

    if not _TRACE_ENABLED:
        sys.settrace(_timeout_trace)
        _TRACE_ENABLED = True

    main_test_task = _get_main_test_task()
    if main_test_task is not None:
        _trace_task(main_test_task)

def _timeout_trace(frame, event, arg):
    if id(frame) in _TRACE_FRAME_IDS:
        raise SimTimeoutError(_SHUTDOWN_MESSAGE)

    return _timeout_trace

def _request_shutdown(signum, frame):
    global _SHUTDOWN_REQUESTED, _SHUTDOWN_MESSAGE

    if not _SHUTDOWN_REQUESTED:
        _SHUTDOWN_REQUESTED = True
        if signum in {
            getattr(signal, "SIGINT", None),
            getattr(signal, "SIGUSR2", None),
        }:
            _SHUTDOWN_MESSAGE = "hdl_runner interrupted by ctrl+C"
        else:
            _SHUTDOWN_MESSAGE = "hdl_runner timeout expired"

    if frame is not None and _frame_in_wrapped_test(frame):
        raise SimTimeoutError(_SHUTDOWN_MESSAGE)

    _enable_timeout_trace()

def _install_signal_handler(signum):
    if signum is not None:
        try:
            signal.signal(signum, _request_shutdown)
        except (AttributeError, OSError, ValueError):
            pass

for _shutdown_signal in (
    getattr(signal, "SIGINT", None),
    getattr(signal, "SIGBREAK", None),
    getattr(signal, "SIGUSR1", None),
    getattr(signal, "SIGUSR2", None),
):
    _install_signal_handler(_shutdown_signal)

def _wrap_func(original_func):
    @functools.wraps(original_func)
    async def wrapper(*args, **kwargs):
        _hdl_runner_timeout_wrapper = True  # Do not touch, used by _frame_in_wrapped_test

        if _SHUTDOWN_REQUESTED:
            raise SimTimeoutError(_SHUTDOWN_MESSAGE)

        return await original_func(*args, **kwargs)

    return wrapper

def _wrap_test(test):
    if hasattr(test, "func"):
        test.func = _wrap_func(test.func)
    elif hasattr(test, "_func"):
        test._func = _wrap_func(test._func)
    else:
        raise TypeError(f"Unsupported cocotb test object: {type(test)!r}")

    return test

_mod = importlib.import_module(_USER_MODULE)

for _name, _obj in list(vars(_mod).items()):
    if isinstance(_obj, Test):
        globals()[_name] = _wrap_test(_obj)
    elif Parameterized and isinstance(_obj, Parameterized):
        _wrap_test(_obj.test_template)
        globals()[_name] = _obj
