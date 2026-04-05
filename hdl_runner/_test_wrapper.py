import functools
import importlib
import os
import signal
import types

try:
    # Cocotb 2.0.1
    from cocotb._decorators import Parameterized, Test
except ImportError:
    # Cocotb 1.9.2
    from cocotb.decorators import test as Test
    Parameterized = ()

_USER_MODULE = os.getenv("HDL_RUNNER_TEST_MODULE", None)
if _USER_MODULE is None:
    raise RuntimeError("Missing HDL_RUNNER_TEST_MODULE definition")

_SHUTDOWN_REQUESTED = False
_SHUTDOWN_MESSAGE = "hdl_runner internal error"

class HDLRunnerError(Exception):
    pass

def _frame_in_wrapped_test(frame):
    while frame is not None:
        if frame.f_locals.get("_hdl_runner_timeout_wrapper", False):
            return True
        frame = frame.f_back
    return False

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
        raise HDLRunnerError(_SHUTDOWN_MESSAGE)
    # _drive_coro handles injection when the coroutine is suspended at await

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

@types.coroutine
def _drive_coro(coro):
    value = None
    while True:
        if _SHUTDOWN_REQUESTED:
            coro.close()
            raise HDLRunnerError(_SHUTDOWN_MESSAGE)
        try:
            yielded = coro.send(value)
        except StopIteration as e:
            return e.value
        try:
            value = yield yielded
        except BaseException:
            coro.close()
            raise

def _wrap_func(original_func):
    @functools.wraps(original_func)
    async def wrapper(*args, **kwargs):
        _hdl_runner_timeout_wrapper = True  # Do not touch, used by _frame_in_wrapped_test
        return await _drive_coro(original_func(*args, **kwargs))

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
