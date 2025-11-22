from celosia import get_lang_map as celosia_get_lang_map
from amaranth.build.plat import Platform as AmaranthPlatform
from amaranth.back import verilog
from celosia import Platform as CelosiaPlatform
from typing import Union

class Backend:

    @staticmethod
    def get_lang_map():
        return {}

    @staticmethod
    def convert_platform(platform: Union[AmaranthPlatform, CelosiaPlatform]):
        return platform


class AmaranthBackend(Backend):
    @staticmethod
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
    
    @staticmethod
    def convert_platform(platform: Union[AmaranthPlatform, CelosiaPlatform]):
        assert platform is None or (isinstance(platform, AmaranthPlatform) and not isinstance(platform, CelosiaPlatform))
        return platform


class CelosiaBackend(Backend):
    @staticmethod
    def get_lang_map():
        return celosia_get_lang_map()

    @staticmethod
    def convert_platform(platform: Union[AmaranthPlatform, CelosiaPlatform]):
        return CelosiaPlatform.from_amaranth_platform(platform)