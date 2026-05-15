import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from common import *

test = generate_tests(
    language = 'vhdl',
    extension = 'vhd',
    backends = [None, 'celosia'],
    simulators = ['nvc', 'ghdl'],
)

if __name__ == '__main__':
    test(8, 'celosia', 'nvc')