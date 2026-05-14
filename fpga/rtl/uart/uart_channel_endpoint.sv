// Buffered UART transport for fixed-size channel frames.
// rx_* fields are decoded channel data received from the uart_rx pin.
// tx_* fields are channel data to send over the uart_tx pin.
// Payload bytes start at the highest byte lane. Hold input frames stable
// until tx_valid && tx_ready; received frames obey the same handshake.
// UART has no flow control: the peer must limit outstanding traffic to avoid
// overflowing the receive byte FIFO while frame delivery is stalled.
module fdk_uart_channel_endpoint #(
    parameter int CLK_FREQ_HZ,
    parameter int CHANNEL_PAYLOAD_BYTES,
    parameter int BAUD_RATE,
    parameter int FRAME_FIFO_DEPTH,
    parameter int RX_FIFO_DEPTH
)
(
    input logic clk,
    input logic rst,
    input logic uart_rx,
    output logic uart_tx,

    output logic [7:0] rx_channel_id,
    output logic rx_sop,
    output logic rx_eop,
    output logic [5:0] rx_reserved,
    output logic [CHANNEL_PAYLOAD_BYTES*8-1:0] rx_data,
    output logic rx_valid,
    input logic rx_ready,

    input logic [7:0] tx_channel_id,
    input logic tx_sop,
    input logic tx_eop,
    input logic [CHANNEL_PAYLOAD_BYTES*8-1:0] tx_data,
    input logic tx_valid,
    output logic tx_ready
);
    logic [7:0] rx_byte;
    logic rx_byte_valid;

    fdk_uart_rx #(
        .CLK_FREQ_HZ(CLK_FREQ_HZ),
        .BAUD_RATE(BAUD_RATE)
    ) receiver (
        .clk(clk),
        .rst(rst),
        .rx(uart_rx),
        .rx_byte(rx_byte),
        .rx_byte_valid(rx_byte_valid),
        .framing_error()
    );

    logic [7:0] buffered_rx_byte;
    logic buffered_rx_valid;
    logic buffered_rx_ready;

    // Absorb brief decoder stalls; UART cannot stop sending if this FIFO fills.
    fdk_registered_fifo #(
        .DATA_WIDTH(8),
        .DEPTH(RX_FIFO_DEPTH)
    ) rx_fifo (
        .clk(clk),
        .rst(rst),
        .in_data(rx_byte),
        .in_valid(rx_byte_valid),
        .in_ready(),
        .out_data(buffered_rx_byte),
        .out_valid(buffered_rx_valid),
        .out_ready(buffered_rx_ready)
    );

    logic [7:0] received_channel_id;
    logic received_sop;
    logic received_eop;
    logic [5:0] received_reserved;
    logic [CHANNEL_PAYLOAD_BYTES*8-1:0] received_data;
    logic received_valid;
    logic received_ready;

    fdk_channel_rx #(
        .INPUT_BEAT_WIDTH(8),
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES)
    ) channel_receiver (
        .clk(clk),
        .rst(rst),
        .in_data(buffered_rx_byte),
        .in_valid(buffered_rx_valid),
        .in_ready(buffered_rx_ready),
        .out_channel_id(received_channel_id),
        .out_sop(received_sop),
        .out_eop(received_eop),
        .out_reserved(received_reserved),
        .out_data(received_data),
        .out_valid(received_valid),
        .out_ready(received_ready)
    );

    fdk_channel_frame_fifo #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .DEPTH(FRAME_FIFO_DEPTH)
    ) rx_frame_fifo (
        .clk(clk),
        .rst(rst),
        .in_channel_id(received_channel_id),
        .in_sop(received_sop),
        .in_eop(received_eop),
        .in_reserved(received_reserved),
        .in_data(received_data),
        .in_valid(received_valid),
        .in_ready(received_ready),
        .out_channel_id(rx_channel_id),
        .out_sop(rx_sop),
        .out_eop(rx_eop),
        .out_reserved(rx_reserved),
        .out_data(rx_data),
        .out_valid(rx_valid),
        .out_ready(rx_ready)
    );

    logic [7:0] queued_channel_id;
    logic queued_sop;
    logic queued_eop;
    logic [CHANNEL_PAYLOAD_BYTES*8-1:0] queued_data;
    logic queued_valid;
    logic queued_ready;

    fdk_channel_frame_fifo #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .DEPTH(FRAME_FIFO_DEPTH)
    ) tx_frame_fifo (
        .clk(clk),
        .rst(rst),
        .in_channel_id(tx_channel_id),
        .in_sop(tx_sop),
        .in_eop(tx_eop),
        .in_reserved(6'b0),
        .in_data(tx_data),
        .in_valid(tx_valid),
        .in_ready(tx_ready),
        .out_channel_id(queued_channel_id),
        .out_sop(queued_sop),
        .out_eop(queued_eop),
        .out_reserved(),
        .out_data(queued_data),
        .out_valid(queued_valid),
        .out_ready(queued_ready)
    );

    logic [7:0] tx_byte;
    logic tx_byte_valid;
    logic tx_byte_ready;

    fdk_channel_tx #(
        .OUTPUT_BEAT_WIDTH(8),
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES)
    ) channel_transmitter (
        .clk(clk),
        .rst(rst),
        .in_channel_id(queued_channel_id),
        .in_sop(queued_sop),
        .in_eop(queued_eop),
        .in_data(queued_data),
        .in_valid(queued_valid),
        .in_ready(queued_ready),
        .out_data(tx_byte),
        .output_byte_count(), // Eight-bit UART words always contain one valid byte.
        .out_valid(tx_byte_valid),
        .out_ready(tx_byte_ready)
    );

    fdk_uart_tx #(
        .CLK_FREQ_HZ(CLK_FREQ_HZ),
        .BAUD_RATE(BAUD_RATE)
    ) transmitter (
        .clk(clk),
        .rst(rst),
        .data(tx_byte),
        .valid(tx_byte_valid),
        .ready(tx_byte_ready),
        .tx(uart_tx)
    );
endmodule
