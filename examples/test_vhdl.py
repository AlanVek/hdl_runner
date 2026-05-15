import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from common import *

from hdl_runner.sim import COCOTB_2_0_0

backends = [None]
if not COCOTB_2_0_0:
    backends.append('celosia')

test = generate_tests(
    language = 'vhdl',
    extension = 'vhd',
    backends = backends,
    simulators = ['nvc', 'ghdl'],
    timescale = ('1ns', '1fs'), # For GHDL+celosia
)

if __name__ == '__main__':
    test(8, 'celosia', 'nvc')