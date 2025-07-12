library ieee;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

entity Adder is
    generic(
        size : integer := 8
    );
    port (
        a    : in  std_logic_vector(size-1 downto 0);
        b    : in  std_logic_vector(size-1 downto 0);
        o    : out std_logic_vector(size downto 0);

        clk  : in std_logic;
        rst  : in std_logic
    );
end Adder;

architecture rtl of Adder is
begin

    addition : process (clk) is
    begin
        if rising_edge(clk) then
            if rst = '1' then
                o <= std_logic_vector(to_unsigned(0, size + 1));
            else
                o <= std_logic_vector(resize(unsigned(a), size+1) + resize(unsigned(b), size+1));
            end if;
        end if;
    end process addition;
end rtl;
