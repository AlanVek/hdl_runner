module Adder
#(
    parameter size = 8
)(
    input wire [size-1:0] a,
    input wire [size-1:0] b,
    output wire [size:0] o,

    input wire clk,
    input wire rst
);

    reg [size:0] o_reg = 0;

    always @(posedge clk) begin
        if (rst == 1)
            o_reg = 0;
        else
            o_reg = a + b;
    end

    assign o = o_reg;

endmodule