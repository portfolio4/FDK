// Packed message-handler beat types. SystemVerilog typedefs cannot take
// parameters, so expand each type at the caller's CHANNEL_PAYLOAD_BYTES width:
// typedef `FDK_MESSAGE_HANDLER_INPUT_BEAT_T(CHANNEL_PAYLOAD_BYTES)
//     fdk_message_handler_input_beat_t;
// typedef `FDK_MESSAGE_HANDLER_OUTPUT_BEAT_T(CHANNEL_PAYLOAD_BYTES)
//     fdk_message_handler_output_beat_t;
// ready travels in the opposite direction and is intentionally a separate port.
`ifndef FDK_MESSAGE_HANDLERS_SV
`define FDK_MESSAGE_HANDLERS_SV

// Incoming payload beats have full-width data, including final-beat padding.
// Preserve the complete incoming header for routing and handler processing.
`define FDK_MESSAGE_HANDLER_INPUT_BEAT_T(PAYLOAD_BYTES) struct packed { \
    logic [(PAYLOAD_BYTES)*8-1:0] data; \
    logic sop; \
    logic eop; \
    logic valid; \
    fdk_message_defines::msg_hdr_msg_size_t msg_size; \
    fdk_message_defines::msg_hdr_seq_t seq; \
    fdk_message_defines::msg_hdr_seq_t ack_seq; \
    fdk_message_defines::msg_hdr_msg_type_t msg_type; \
}

`define FDK_MESSAGE_HANDLER_OUTPUT_BEAT_T(PAYLOAD_BYTES) struct packed { \
    logic [(PAYLOAD_BYTES)*8-1:0] data; \
    logic [$clog2((PAYLOAD_BYTES)+1)-1:0] data_len; \
    logic sop; \
    logic eop; \
    logic valid; \
    fdk_message_defines::msg_hdr_msg_size_t msg_size; \
    fdk_message_defines::msg_hdr_seq_t ack_seq; \
    fdk_message_defines::msg_hdr_msg_type_t msg_type; \
}

`endif
