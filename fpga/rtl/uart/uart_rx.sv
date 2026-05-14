module fdk_uart_rx #(
    parameter int CLK_FREQ_HZ,
    parameter int BAUD_RATE
)
(
    input logic clk,
    input logic rst,

    input logic rx,
    output logic [7:0] rx_byte,
    output logic rx_byte_valid,
    output logic framing_error
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
        RECEIVE_START_BIT,
        RECEIVE_PAYLOAD_BIT,
        RECEIVE_STOP_BIT
    } state_t;
    state_t state = IDLE;

    logic [31:0] receive_bit_timer = '0;
    logic [2:0] receive_bit_index = '0;

    // rx might not be metastable, so put it into rx_sync[0]
    // rx_sync[1] is the stable bit that we received the previous cycle
    (* ASYNC_REG = "TRUE" *) logic [1:0] rx_sync = 2'b11;

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            receive_bit_timer <= 0;
            receive_bit_index <= 0;
            rx_sync <= 2'b11;
            rx_byte_valid <= 0;
            framing_error <= 0;
        end else begin
            rx_sync <= {rx_sync[0], rx};
            rx_byte_valid <= 0;
            framing_error <= 0;

            case (state)
                IDLE: begin
                    if (rx_sync[1] == 0) begin
                        // divide by 2 so that we synchronize to the middle
                        // of the WAIT_CYCLES_BETWEEN_TX_BITS window.
                        // We don't want to sample bits at the start/end of
                        // the window because they might not be stable
                        receive_bit_timer <= WAIT_CYCLES_BETWEEN_TX_BITS / 32'd2 - 32'd1;
                        state <= RECEIVE_START_BIT;
                    end
                end

                RECEIVE_START_BIT: begin
                    if (receive_bit_timer != 32'd0) begin
                        // still waiting to sync to middle of window
                        receive_bit_timer <= receive_bit_timer - 32'd1;
                    end else begin
                        // else, we are at the middle of the window now
                        if (rx_sync[1] == 0) begin
                            // received correct start bit, transition to
                            // receiving payload bits
                            receive_bit_timer <= WAIT_CYCLES_BETWEEN_TX_BITS - 32'd1;
                            receive_bit_index <= '0;
                            state <= RECEIVE_PAYLOAD_BIT;
                        end else begin
                            // we received a 1 bit, which is not correct, so
                            // this was an unstable/fake start, back to IDLE
                            state <= IDLE;
                        end
                    end
                end

                RECEIVE_PAYLOAD_BIT: begin
                    if (receive_bit_timer != 32'd0) begin
                        receive_bit_timer <= receive_bit_timer - 32'd1;
                    end else begin
                        rx_byte[receive_bit_index] <= rx_sync[1];
                        receive_bit_timer <= WAIT_CYCLES_BETWEEN_TX_BITS - 32'd1;
                        if (receive_bit_index == 3'd7) begin
                            state <= RECEIVE_STOP_BIT;
                        end else begin
                            receive_bit_index <= receive_bit_index + 3'd1;
                        end
                    end
                end

                RECEIVE_STOP_BIT: begin
                    if (receive_bit_timer != 32'd0) begin
                        receive_bit_timer <= receive_bit_timer - 32'd1;
                    end else begin
                        if (rx_sync[1] == 1'b1) begin
                            rx_byte_valid <= 1;
                            framing_error <= 0;
                        end else begin
                            rx_byte_valid <= 0;
                            framing_error <= 1;
                        end
                        state <= IDLE;
                    end
                end
            endcase
        end
    end
endmodule
