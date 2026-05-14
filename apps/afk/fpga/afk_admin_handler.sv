// Receive ADMIN channel frames and stream echo payloads through the shared handler.
// TestRequest produces a header-only Ack after its input EOP.
module afk_admin_handler #(
    parameter int CHANNEL_PAYLOAD_BYTES,
    parameter type fdk_message_handler_input_beat_t =
        `FDK_MESSAGE_HANDLER_INPUT_BEAT_T(CHANNEL_PAYLOAD_BYTES),
    parameter type fdk_message_handler_output_beat_t =
        `FDK_MESSAGE_HANDLER_OUTPUT_BEAT_T(CHANNEL_PAYLOAD_BYTES)
)
(
    input logic clk,
    input logic rst,
    input logic [CHANNEL_PAYLOAD_BYTES*8-1:0] in_data,
    input logic in_sop,
    input logic in_eop,
    input logic in_valid,
    output logic in_ready,
    output logic [CHANNEL_PAYLOAD_BYTES*8-1:0] out_data,
    output logic out_sop,
    output logic out_eop,
    output logic out_valid,
    input logic out_ready
);

    fdk_message_handler_input_beat_t in_beat;
    fdk_message_handler_output_beat_t out_beat;
    logic message_ready, message_output_ready;
    fdk_message_defines::msg_hdr_seq_t send_seq_ff;

    fdk_message_rx #(.CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES)) message_receiver (
        .clk(clk), .rst(rst),
        .in_data(in_data), .in_sop(in_sop), .in_eop(in_eop),
        .in_valid(in_valid), .in_ready(in_ready),
        .out_msg_size(in_beat.msg_size), .out_seq(in_beat.seq),
        .out_ack_seq(in_beat.ack_seq), .out_msg_type(in_beat.msg_type),
        .out_data(in_beat.data), .out_sop(in_beat.sop), .out_eop(in_beat.eop),
        .out_valid(in_beat.valid), .out_ready(message_ready)
    );
    always_ff @(posedge clk) begin
        if (rst) begin
            send_seq_ff <= '0;
        end else if (out_beat.valid && message_output_ready && out_beat.eop) begin
            send_seq_ff <= send_seq_ff + fdk_message_defines::msg_hdr_seq_t'(out_beat.msg_size);
        end
    end

    fdk_message_handler_input_beat_t echo_input, test_input;
    fdk_message_handler_output_beat_t echo_output, test_output;
    logic echo_ready, echo_output_ready, test_ready, test_output_ready;

    fdk_message_echo_request_handler #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .fdk_message_handler_input_beat_t(fdk_message_handler_input_beat_t),
        .fdk_message_handler_output_beat_t(fdk_message_handler_output_beat_t)
    ) echo_handler (
        .clk(clk), .rst(rst), .in_beat(echo_input), .in_ready(echo_ready),
        .out_beat(echo_output), .out_ready(echo_output_ready)
    );
    test_request_handler #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .fdk_message_handler_input_beat_t(fdk_message_handler_input_beat_t),
        .fdk_message_handler_output_beat_t(fdk_message_handler_output_beat_t)
    ) test_handler (
        .clk(clk), .rst(rst), .in_beat(test_input), .in_ready(test_ready),
        .out_beat(test_output), .out_ready(test_output_ready)
    );

    // select which handler gets the inputs based on the input message type
    always_comb begin
        echo_input = '0;
        test_input = '0;
        message_ready = !rst;
        if (in_beat.msg_type == fdk_message_defines::ECHO_REQUEST_MSG_TYPE &&
            in_beat.msg_size == fdk_message_defines::msg_hdr_msg_size_t'(fdk_message_defines::ECHO_REQUEST_MESSAGE_BYTES)) begin
            echo_input = in_beat;
            message_ready = echo_ready;
        end else if (in_beat.msg_type == afk_message_defines::TEST_REQUEST_MSG_TYPE &&
            in_beat.msg_size == fdk_message_defines::msg_hdr_msg_size_t'(afk_message_defines::TEST_REQUEST_MESSAGE_BYTES)) begin
            test_input = in_beat;
            message_ready = test_ready;
        end
    end

    // Arbitrate complete responses, preserving payload and metadata through EOP.
    fdk_message_handler_output_beat_t response_arbiter_output;
    logic response_arbiter_output_valid;
    fdk_packet_rr_arbiter #(
        .NUM_INPUTS(2),
        .DATA_WIDTH($bits(fdk_message_handler_output_beat_t))
    ) response_arbiter (
        .clk(clk), .rst(rst),
        .in_data('{echo_output, test_output}),
        .in_valid({test_output.valid, echo_output.valid}),
        .in_eop({test_output.eop, echo_output.eop}),
        .in_ready({test_output_ready, echo_output_ready}),
        .out_data(response_arbiter_output), .out_valid(response_arbiter_output_valid),
        .out_ready(message_output_ready)
    );
    always_comb begin
        out_beat = response_arbiter_output;
        out_beat.valid = response_arbiter_output_valid;
    end

    assert property (@(posedge clk) disable iff (rst)
        (out_beat.valid && !message_output_ready) |=> out_beat.valid && $stable(out_beat));

    fdk_message_tx #(.CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES)) message_transmitter (
        .clk(clk), .rst(rst),
        .in_seq(send_seq_ff), .in_ack_seq(out_beat.ack_seq),
        .in_msg_size(out_beat.msg_size), .in_msg_type(out_beat.msg_type),
        .in_data(out_beat.data), .in_data_len(out_beat.data_len),
        .in_sop(out_beat.sop), .in_eop(out_beat.eop),
        .in_valid(out_beat.valid), .in_ready(message_output_ready),
        .out_data(out_data), .out_sop(out_sop), .out_eop(out_eop),
        .out_valid(out_valid), .out_ready(out_ready)
    );
endmodule

// A header-only TestRequest becomes one zero-byte Ack payload beat.
module test_request_handler #(
    parameter int CHANNEL_PAYLOAD_BYTES,
    parameter type fdk_message_handler_input_beat_t =
        `FDK_MESSAGE_HANDLER_INPUT_BEAT_T(CHANNEL_PAYLOAD_BYTES),
    parameter type fdk_message_handler_output_beat_t =
        `FDK_MESSAGE_HANDLER_OUTPUT_BEAT_T(CHANNEL_PAYLOAD_BYTES)
)
(
    input logic clk,
    input logic rst,
    input fdk_message_handler_input_beat_t in_beat,
    output logic in_ready,
    output fdk_message_handler_output_beat_t out_beat,
    input logic out_ready
);
    logic valid_ff;
    fdk_message_defines::msg_hdr_seq_t ack_seq_ff;

    assign in_ready = !rst && (!valid_ff || out_ready);
    always_comb begin
        out_beat = '0;
        out_beat.valid = !rst && valid_ff;
        out_beat.sop = 1;
        out_beat.eop = 1;
        out_beat.msg_size = fdk_message_defines::msg_hdr_msg_size_t'(afk_message_defines::ACK_MESSAGE_BYTES);
        out_beat.ack_seq = ack_seq_ff;
        out_beat.msg_type = afk_message_defines::ACK_MSG_TYPE;
    end
    always_ff @(posedge clk) begin
        if (rst) begin
            valid_ff <= 0;
            ack_seq_ff <= '0;
        end else if (in_ready) begin
            valid_ff <= in_beat.valid;
            if (in_beat.valid) begin
                ack_seq_ff <= in_beat.seq;
            end
        end
    end
endmodule
