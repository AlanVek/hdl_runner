import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from common import *

test = generate_tests(
    language = 'verilog',
    extension = 'v',
    backends = ['celosia', 'amaranth', None],
    simulators = ['icarus', 'verilator'],
)

if __name__ == '__main__':
    test(8, 'amaranth', 'icarus')