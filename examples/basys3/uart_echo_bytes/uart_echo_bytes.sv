module uart_echo_bytes (
    input  logic clk,
    input  logic rst,
    input logic rx,
    output logic tx
);
    import basys3_constants::CLK_FREQ_HZ;
    import basys3_constants::BAUD_RATE;

    logic [7:0] rx_byte;
    logic rx_byte_valid;
    logic rx_framing_error;

    fdk_uart_rx #(
        .CLK_FREQ_HZ(CLK_FREQ_HZ),
        .BAUD_RATE(BAUD_RATE)
    ) receiver (
        .clk(clk),
        .rst(rst),
        .rx(rx),
        .rx_byte(rx_byte),
        .rx_byte_valid(rx_byte_valid),
        .framing_error(rx_framing_error)
    );

    logic tx_ready;
    logic tx_valid;
    logic [7:0] tx_byte;

    fdk_uart_tx #(
        .CLK_FREQ_HZ(CLK_FREQ_HZ),
        .BAUD_RATE(BAUD_RATE)
    ) transmitter (
        .clk(clk),
        .rst(rst),
        .data(tx_byte),
        .valid(tx_valid),
        .ready(tx_ready),
        .tx(tx)
    );


    logic [7:0] buffer [0:255];
    logic [8:0] rx_buffer_idx;
    logic [8:0] tx_buffer_idx;

    logic empty;
    assign empty = (rx_buffer_idx == tx_buffer_idx);
    logic full;
    assign full = (rx_buffer_idx[7:0] == tx_buffer_idx[7:0] && rx_buffer_idx[8] != tx_buffer_idx[8]);

    assign tx_valid = !rst && !empty;
    assign tx_byte = buffer[tx_buffer_idx[7:0]];

    logic tx_should_deque;
    assign tx_should_deque = (tx_valid && tx_ready);

    always_ff @(posedge clk) begin
        if (rst) begin
            rx_buffer_idx <= 0;
            tx_buffer_idx <= 0;
        end else begin
            // note: if queue is full, but tx will transmit a byte this cycle,
            // then we can still write another rx byte into the slot that was
            // just transmitted
            if (rx_byte_valid && (!full || tx_should_deque)) begin
                buffer[rx_buffer_idx[7:0]] <= rx_byte;
                rx_buffer_idx <= rx_buffer_idx + 8'd1;
            end

            if (tx_should_deque) begin
                tx_buffer_idx <= tx_buffer_idx + 8'd1;
            end
        end
    end
endmodule
