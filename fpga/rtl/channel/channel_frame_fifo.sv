// Queue fixed-size channel frames, preserving all descriptor bits.
// The output is registered; DEPTH storage entries plus the output slot retain frames.
module fdk_channel_frame_fifo #(
    parameter int CHANNEL_PAYLOAD_BYTES,
    parameter int DEPTH
)
(
    input logic clk,
    input logic rst,

    input logic [7:0] in_channel_id,
    input logic in_sop,
    input logic in_eop,
    input logic [5:0] in_reserved,
    input logic [CHANNEL_PAYLOAD_BYTES*8-1:0] in_data,
    input logic in_valid,
    output logic in_ready,

    output logic [7:0] out_channel_id,
    output logic out_sop,
    output logic out_eop,
    output logic [5:0] out_reserved,
    output logic [CHANNEL_PAYLOAD_BYTES*8-1:0] out_data,
    output logic out_valid,
    input logic out_ready
);
    initial begin
        assert(CHANNEL_PAYLOAD_BYTES > 0)
            else $fatal(1, "CHANNEL_PAYLOAD_BYTES must be positive");
    end

    localparam int DATA_WIDTH = (CHANNEL_PAYLOAD_BYTES + 2) * 8;

    logic [DATA_WIDTH-1:0] fifo_in_data;
    assign fifo_in_data = {
        in_channel_id,
        in_reserved,
        in_eop,
        in_sop,
        in_data
    };

    logic [DATA_WIDTH-1:0] fifo_out_data;
    assign {
        out_channel_id,
        out_reserved,
        out_eop,
        out_sop,
        out_data
    } = fifo_out_data;

    fdk_registered_fifo #(
        .DATA_WIDTH(DATA_WIDTH),
        .DEPTH(DEPTH)
    ) internal_fifo (
        .clk(clk),
        .rst(rst),

        .in_data(fifo_in_data),
        .in_valid(in_valid),
        .in_ready(in_ready),

        .out_data(fifo_out_data),
        .out_valid(out_valid),
        .out_ready(out_ready)
    );
endmodule
