// RTL message wire types. Host types must match this layout before use.
package fdk_message_defines;
    typedef logic [15:0] msg_hdr_msg_size_t;
    typedef logic [31:0] msg_hdr_seq_t;
    typedef logic [15:0] msg_hdr_msg_type_t;

    // Used for both numeric fields and little-endian wire bytes. Use
    // byteswap_header() to convert between the two representations when wire
    // bytes occupy MSB-first lanes; field order stays the same.
    typedef struct packed {
        // Entire message in bytes, including this header, excluding channel padding.
        msg_hdr_msg_size_t msg_size;
        msg_hdr_seq_t seq;
        msg_hdr_seq_t ack_seq;
        msg_hdr_msg_type_t msg_type;
    } msg_header_t;

    // Combinational byte reversal within each field. The same operation encodes
    // and decodes: applying it twice returns the original header.
    function automatic msg_header_t byteswap_header(input msg_header_t header);
        msg_header_t swapped;
        swapped.msg_size = {<<8{header.msg_size}};
        swapped.seq = {<<8{header.seq}};
        swapped.ack_seq = {<<8{header.ack_seq}};
        swapped.msg_type = {<<8{header.msg_type}};
        return swapped;
    endfunction

    localparam int MSG_HDR_MSG_SIZE_BITS = $bits(msg_hdr_msg_size_t);
    localparam int MSG_HDR_MSG_SIZE_BYTES = MSG_HDR_MSG_SIZE_BITS / 8;
    localparam int MSG_HDR_SEQ_BITS = $bits(msg_hdr_seq_t);
    localparam int MSG_HDR_SEQ_BYTES = MSG_HDR_SEQ_BITS / 8;
    localparam int MSG_HDR_MSG_TYPE_BITS = $bits(msg_hdr_msg_type_t);
    localparam int MSG_HDR_MSG_TYPE_BYTES = MSG_HDR_MSG_TYPE_BITS / 8;
    localparam int MSG_HEADER_BITS = $bits(msg_header_t);
    localparam int MSG_HEADER_BYTES = MSG_HEADER_BITS / 8;

    // Byte offsets from the start of the serialized message header.
    localparam int MSG_HDR_MSG_SIZE_OFFSET_BYTES = 0;
    localparam int MSG_HDR_SEQ_OFFSET_BYTES = MSG_HDR_MSG_SIZE_BYTES;
    localparam int MSG_HDR_ACK_SEQ_OFFSET_BYTES = MSG_HDR_SEQ_OFFSET_BYTES + MSG_HDR_SEQ_BYTES;
    localparam int MSG_HDR_MSG_TYPE_OFFSET_BYTES = MSG_HDR_ACK_SEQ_OFFSET_BYTES + MSG_HDR_SEQ_BYTES;

    // Numeric IDs; use byteswap_header() when converting a header to wire bytes.
    localparam msg_hdr_msg_type_t ECHO_REQUEST_MSG_TYPE = 16'd1;
    localparam msg_hdr_msg_type_t ECHO_RESPONSE_MSG_TYPE = 16'd2;
    localparam msg_hdr_msg_type_t APP_SPECIFIC_MSG_TYPE_0 = 16'd2048;
    localparam msg_hdr_msg_type_t APP_SPECIFIC_MSG_TYPE_1 = 16'd2049;
    localparam msg_hdr_msg_type_t APP_SPECIFIC_MSG_TYPE_2 = 16'd2050;
    localparam msg_hdr_msg_type_t APP_SPECIFIC_MSG_TYPE_3 = 16'd2051;
    localparam msg_hdr_msg_type_t APP_SPECIFIC_MSG_TYPE_4 = 16'd2052;
    localparam msg_hdr_msg_type_t APP_SPECIFIC_MSG_TYPE_5 = 16'd2053;
    localparam msg_hdr_msg_type_t APP_SPECIFIC_MSG_TYPE_6 = 16'd2054;

    localparam int ECHO_PAYLOAD_BYTES = 128;
    localparam int ECHO_PAYLOAD_BITS = ECHO_PAYLOAD_BYTES * 8;
    // First payload byte is payload[ECHO_PAYLOAD_BYTES-1], matching the channel
    // library's convention that the first byte occupies the highest byte lane.
    typedef logic [ECHO_PAYLOAD_BYTES-1:0][7:0] echo_payload_t;

    // These bodies correspond to C++ EchoRequest and EchoResponse, without the
    // Message<T> header. Packed structs introduce no padding.
    typedef struct packed {
        echo_payload_t payload;
    } echo_request_t;

    typedef struct packed {
        echo_payload_t payload;
    } echo_response_t;

    // Concrete counterparts of Message<EchoRequest> and Message<EchoResponse>.
    typedef struct packed {
        msg_header_t msg_hdr;
        echo_request_t msg;
    } echo_request_message_t;

    typedef struct packed {
        msg_header_t msg_hdr;
        echo_response_t msg;
    } echo_response_message_t;

    localparam int ECHO_REQUEST_MESSAGE_BITS = $bits(echo_request_message_t);
    localparam int ECHO_REQUEST_MESSAGE_BYTES = ECHO_REQUEST_MESSAGE_BITS / 8;
    localparam int ECHO_RESPONSE_MESSAGE_BITS = $bits(echo_response_message_t);
    localparam int ECHO_RESPONSE_MESSAGE_BYTES = ECHO_RESPONSE_MESSAGE_BITS / 8;
endpackage
