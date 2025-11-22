from amaranth import Signal
from amaranth.build.plat import Platform as AmaranthPlatform
from celosia import Platform as CelosiaPlatform
from typing import Union
from hdl_runner.backend import *

try:
    from amaranth.hdl._ast import SignalDict, SignalKey
except ImportError:
    from amaranth.hdl.ast import SignalDict, SignalKey

def open_ports(ports) -> list:
    """
    Recursively unwraps and collects all Amaranth Signals from the given ports structure.
    Accepts lists, tuples, dicts, Records, SignalDicts, SignalKeys, etc.

    Args:
        ports: The ports structure to unwrap.

    Returns:
        List of Signal objects.
    """

    if isinstance(ports, (int, str, float)):
        raise ValueError(f"Invalid port: {ports}")

    if hasattr(ports, 'as_value') and callable(ports.as_value):
        ports = ports.as_value()

    if isinstance(ports, Signal):
        return [ports]

    if hasattr(ports, '_lhs_signals') and callable(ports._lhs_signals):
        ports = ports._lhs_signals()

    if isinstance(ports, SignalKey):
        ports = [ports.signal]

    if isinstance(ports, SignalDict):
        ports = ports.keys()
    elif isinstance(ports, dict):
        ports = ports.values()

    res = []
    try:
        for pin in ports:
            res += open_ports(pin)
    except TypeError:
        raise ValueError("Invalid ports received!") from None

    return res

def _get_backend(backend: str = None) -> Backend:
    # Default backend is amaranth
    if backend is None or backend == 'amaranth':
        return AmaranthBackend()
    
    if backend == 'celosia':
        return CelosiaBackend()
    
    raise ValueError(f"Unknown backend: {backend}")

def get_lang_map(backend: str = None):
    return _get_backend(backend).get_lang_map()

def convert_platform(platform: Union[AmaranthPlatform, CelosiaPlatform], backend: str):
    return _get_backend(backend).convert_platform(platform)