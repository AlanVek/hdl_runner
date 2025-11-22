from amaranth import Signal
from amaranth.back import verilog

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

def get_lang_map():
    """
    Returns a mapping of HDL language names to converter classes.
    """
    class VerilogConverter:
        extensions = ('v',)
        default_extension = 'v'

        def convert(self, *args, **kwargs):
            return verilog.convert(*args, **kwargs)

    class VHDLConverter:
        extensions = ('vhd', 'vhdl')
        default_extension = 'vhd'

        def convert(self, *args, **kwargs):
            raise NotImplementedError("Amaranth to VHDL not supported")

    return {
        'verilog': VerilogConverter,
        'vhdl': VHDLConverter,
    }
