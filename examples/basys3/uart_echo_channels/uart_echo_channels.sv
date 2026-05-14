module uart_echo_channels #(
    parameter int CLK_FREQ_HZ = basys3_constants::CLK_FREQ_HZ,
    parameter int BAUD_RATE = basys3_constants::BAUD_RATE,
    parameter int CHANNEL_PAYLOAD_BYTES = basys3_constants::CHANNEL_PAYLOAD_BYTES
)
(
    input logic clk,
    input logic rst,
    input logic rx,
    output logic tx
);
    logic [7:0] request_channel_id;
    logic request_sop;
    logic request_eop;
    logic [CHANNEL_PAYLOAD_BYTES*8-1:0] request_data;
    logic request_valid;
    logic request_ready;

    logic [7:0] response_channel_id;
    logic response_sop;
    logic response_eop;
    logic [CHANNEL_PAYLOAD_BYTES*8-1:0] response_data;
    logic response_valid;
    logic response_ready;

    fdk_uart_channel_endpoint #(
        .CLK_FREQ_HZ(CLK_FREQ_HZ),
        .BAUD_RATE(BAUD_RATE),
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .FRAME_FIFO_DEPTH(4),
        .RX_FIFO_DEPTH(256)
    ) transport (
        .clk(clk),
        .rst(rst),
        .uart_rx(rx),
        .uart_tx(tx),
        .rx_channel_id(request_channel_id),
        .rx_sop(request_sop),
        .rx_eop(request_eop),
        .rx_reserved(),
        .rx_data(request_data),
        .rx_valid(request_valid),
        .rx_ready(request_ready),
        .tx_channel_id(response_channel_id),
        .tx_sop(response_sop),
        .tx_eop(response_eop),
        .tx_data(response_data),
        .tx_valid(response_valid),
        .tx_ready(response_ready)
    );

    request_handler #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES)
    ) handler (
        .clk(clk),
        .rst(rst),
        .in_channel_id(request_channel_id),
        .in_sop(request_sop),
        .in_eop(request_eop),
        .in_data(request_data),
        .in_valid(request_valid),
        .in_ready(request_ready),
        .out_channel_id(response_channel_id),
        .out_sop(response_sop),
        .out_eop(response_eop),
        .out_data(response_data),
        .out_valid(response_valid),
        .out_ready(response_ready)
    );
endmodule
