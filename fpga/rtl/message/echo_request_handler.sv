// Registered echo relay. Forward boundaries and limit valid response bytes.
module fdk_message_echo_request_handler #(
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
    localparam int RESPONSE_PAYLOAD_BYTES = fdk_message_defines::ECHO_RESPONSE_MESSAGE_BYTES -
        fdk_message_defines::MSG_HEADER_BYTES;
    typedef logic [$clog2(RESPONSE_PAYLOAD_BYTES+1)-1:0] payload_count_t;
    payload_count_t total_bytes_sent_ff;

    assign in_ready = !rst && (!out_beat.valid || out_ready);
    assign out_beat.msg_size = fdk_message_defines::msg_hdr_msg_size_t'(
        fdk_message_defines::ECHO_RESPONSE_MESSAGE_BYTES);
    assign out_beat.msg_type = fdk_message_defines::ECHO_RESPONSE_MSG_TYPE;

    always_ff @(posedge clk) begin
        if (rst) begin
            total_bytes_sent_ff <= '0;
            out_beat.ack_seq <= '0;
            out_beat.data <= '0;
            out_beat.data_len <= '0;
            out_beat.sop <= 0;
            out_beat.eop <= 0;
            out_beat.valid <= 0;
        end else if (in_ready) begin
            out_beat.valid <= in_beat.valid;
            if (in_beat.valid) begin
                out_beat.data <= in_beat.data;
                if (in_beat.sop) begin
                    out_beat.ack_seq <= in_beat.seq;
                end
                assert(int'(total_bytes_sent_ff) <= RESPONSE_PAYLOAD_BYTES);
                if (int'(total_bytes_sent_ff) + CHANNEL_PAYLOAD_BYTES > RESPONSE_PAYLOAD_BYTES) begin
                    out_beat.data_len <= $bits(out_beat.data_len)'(RESPONSE_PAYLOAD_BYTES - int'(total_bytes_sent_ff));
                    total_bytes_sent_ff <= total_bytes_sent_ff + payload_count_t'(RESPONSE_PAYLOAD_BYTES - int'(total_bytes_sent_ff));
                end else begin
                    out_beat.data_len <= $bits(out_beat.data_len)'(CHANNEL_PAYLOAD_BYTES);
                    total_bytes_sent_ff <= total_bytes_sent_ff + payload_count_t'(CHANNEL_PAYLOAD_BYTES);
                end
                out_beat.sop <= in_beat.sop;
                out_beat.eop <= in_beat.eop;
                if (in_beat.eop) begin
                    total_bytes_sent_ff <= '0;
                end
            end
        end
    end
endmodule
