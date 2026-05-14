module fdk_uart_tx #(
    parameter int CLK_FREQ_HZ,
    parameter int BAUD_RATE
) (
    input  logic       clk,
    input  logic       rst,

    input  logic [7:0] data,
    input  logic       valid,
    output logic       ready,

    output logic       tx
);

    // assume truncation will be fine, we are not going to support an insanely high
    // baud rate where truncation would cause a large error
    localparam int WAIT_CYCLES_BETWEEN_TX_BITS = CLK_FREQ_HZ / BAUD_RATE;
    initial begin
        assert(CLK_FREQ_HZ > 0);
        assert(BAUD_RATE > 0);
        // catch cases where truncation might not be fine
        assert(WAIT_CYCLES_BETWEEN_TX_BITS > 10);
    end

    typedef enum logic [1:0] {
        IDLE,
        TRANSMIT,
        TRANSMIT_STOP_WAIT
    } state_t;
    state_t state = IDLE;

    logic [7:0] buffered_data;
    logic [3:0] tx_data_idx;
    logic [31:0] tx_wait_timer;

    assign ready = (!rst && (state == IDLE));

    always_ff @(posedge clk) begin
        if (rst) begin
            tx <= 1'b1;
            state <= IDLE;
            buffered_data <= 0;
            tx_data_idx <= 0;
            tx_wait_timer <= 0;
        end else begin
            // UART transmits 1 byte at a time.
            //
            // While the line is IDLE, we are constantly transmitting 1s.
            //
            // When we have actual data, we
            //   1. transmit a 0-bit to indicate start
            //   2. transmit 8 bits of data
            //   3. transmit a 1-bit to indicate stop
            //
            // Every bit is held steady for an entire BAUD period
            case (state)
                IDLE: begin
                    if (valid) begin
                        buffered_data <= data;
                        tx_data_idx <= 4'd0;

                        // transmit the start bit
                        tx <= 1'b0;
                        tx_wait_timer <= WAIT_CYCLES_BETWEEN_TX_BITS;
                        state <= TRANSMIT;
                    end
                end

                TRANSMIT: begin
                    tx_wait_timer <= tx_wait_timer - 32'd1;

                    // reached end of a BAUD period
                    if (tx_wait_timer == 32'd1) begin
                        tx_data_idx <= tx_data_idx + 4'b1;

                        // transmit the user data
                        if (tx_data_idx <= 4'd7) begin
                            tx <= buffered_data[3'(tx_data_idx)];
                            tx_wait_timer <= WAIT_CYCLES_BETWEEN_TX_BITS;

                        // all 8 bits of user data transmitted, so now transmit
                        // the stop bit
                        end else begin
                            tx <= 1'b1;
                            tx_wait_timer <= WAIT_CYCLES_BETWEEN_TX_BITS;
                            state <= TRANSMIT_STOP_WAIT;
                        end
                    end
                end

                TRANSMIT_STOP_WAIT: begin
                    tx_wait_timer <= tx_wait_timer - 32'd1;
                    if (tx_wait_timer == 32'd1) begin
                        state <= IDLE;
                    end
                end

                default: begin
                    assert(0)
                        else $fatal(1, "Illegal fdk_uart_tx state: %0d", state);
                end
            endcase
        end
    end
endmodule
