// Route supported channels and message types to application handlers.
// Unhandled traffic is accepted and discarded.
module request_handler #(
    parameter int CHANNEL_PAYLOAD_BYTES
)
(
    input logic clk,
    input logic rst,

    input logic [7:0] in_channel_id,
    input logic in_sop,
    input logic in_eop,
    input logic [CHANNEL_PAYLOAD_BYTES*8-1:0] in_data,
    input logic in_valid,
    output logic in_ready,

    output logic [7:0] out_channel_id,
    output logic out_sop,
    output logic out_eop,
    output logic [CHANNEL_PAYLOAD_BYTES*8-1:0] out_data,
    output logic out_valid,
    input logic out_ready
);
    localparam logic [7:0] ECHO_CHANNEL_ID = 8'd5;
    typedef `FDK_MESSAGE_HANDLER_INPUT_BEAT_T(CHANNEL_PAYLOAD_BYTES)
        fdk_message_handler_input_beat_t;
    typedef `FDK_MESSAGE_HANDLER_OUTPUT_BEAT_T(CHANNEL_PAYLOAD_BYTES)
        fdk_message_handler_output_beat_t;

    logic channel_valid, channel_ready;
    fdk_message_handler_input_beat_t message_input, echo_input;
    logic message_ready, echo_ready;
    fdk_message_handler_output_beat_t echo_response, response;
    logic echo_response_ready, response_ready;
    fdk_message_defines::msg_hdr_msg_size_t response_msg_size_ff, response_msg_size;
    fdk_message_defines::msg_hdr_seq_t response_ack_seq_ff;
    fdk_message_defines::msg_hdr_msg_type_t response_msg_type_ff;
    fdk_message_defines::msg_hdr_seq_t response_ack_seq;
    fdk_message_defines::msg_hdr_msg_type_t response_msg_type;
    fdk_message_defines::msg_hdr_seq_t send_seq_ff, response_bytes_ff, response_bytes;

    // Route channels, then message types, in one place. Unsupported channel
    // frames and unsupported messages on a routed channel are discarded.
    always_comb begin
        in_ready = !rst;
        channel_valid = 0;
        message_ready = 0;
        echo_input = '0;
        echo_response_ready = 0;
        response = '0;

        if (in_channel_id == ECHO_CHANNEL_ID) begin
            in_ready = !rst && channel_ready;
            channel_valid = in_valid;
            message_ready = 1;
            if (message_input.msg_type == fdk_message_defines::ECHO_REQUEST_MSG_TYPE) begin
                echo_input = message_input;
                message_ready = echo_ready;
                response = echo_response;
                echo_response_ready = response_ready;
            end
        end
    end

    // The caller must keep the channel ID associated with pending responses.
    assign out_channel_id = in_channel_id;

    fdk_message_rx #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES)
    ) message_receiver (
        .clk(clk), .rst(rst),
        .in_data(in_data), .in_sop(in_sop), .in_eop(in_eop),
        .in_valid(channel_valid), .in_ready(channel_ready),
        .out_msg_size(message_input.msg_size),
        .out_seq(message_input.seq), .out_ack_seq(message_input.ack_seq),
        .out_msg_type(message_input.msg_type),
        .out_data(message_input.data), .out_sop(message_input.sop), .out_eop(message_input.eop),
        .out_valid(message_input.valid), .out_ready(message_ready)
    );

    fdk_message_echo_request_handler #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .fdk_message_handler_input_beat_t(fdk_message_handler_input_beat_t),
        .fdk_message_handler_output_beat_t(fdk_message_handler_output_beat_t)
    ) echo_handler (
        .clk(clk), .rst(rst),
        .in_beat(echo_input), .in_ready(echo_ready),
        .out_beat(echo_response), .out_ready(echo_response_ready)
    );

    // Keep the selected metadata through the whole response input stream.
    assign response_msg_size = response.valid && response.sop ? response.msg_size : response_msg_size_ff;
    assign response_ack_seq = response.valid && response.sop ? response.ack_seq : response_ack_seq_ff;
    assign response_msg_type = response.valid && response.sop ? response.msg_type : response_msg_type_ff;
    assign response_bytes = (response.sop ? fdk_message_defines::msg_hdr_seq_t'(
        fdk_message_defines::MSG_HEADER_BYTES) : response_bytes_ff) +
        fdk_message_defines::msg_hdr_seq_t'(response.data_len);

    always_ff @(posedge clk) begin
        if (rst) begin
            send_seq_ff <= '0;
            response_bytes_ff <= '0;
            response_msg_size_ff <= '0;
            response_ack_seq_ff <= '0;
            response_msg_type_ff <= '0;
        end else if (response.valid && response_ready) begin
            if (response.sop) begin
                response_msg_size_ff <= response.msg_size;
                response_ack_seq_ff <= response.ack_seq;
                response_msg_type_ff <= response.msg_type;
            end
            response_bytes_ff <= response_bytes;
            if (response.eop) begin
                send_seq_ff <= send_seq_ff + response_bytes;
            end
        end
    end

    fdk_message_tx #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES)
    ) message_transmitter (
        .clk(clk), .rst(rst),
        .in_msg_size(response_msg_size),
        .in_seq(send_seq_ff), .in_ack_seq(response_ack_seq), .in_msg_type(response_msg_type),
        .in_data(response.data), .in_data_len(response.data_len),
        .in_sop(response.sop), .in_eop(response.eop),
        .in_valid(response.valid), .in_ready(response_ready),
        .out_data(out_data), .out_sop(out_sop), .out_eop(out_eop),
        .out_valid(out_valid), .out_ready(out_ready)
    );
endmodule
