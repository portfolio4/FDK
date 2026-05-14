// Logical service channels shared with apps/afk/server/include/afk/fpga/Channel.h.
package afk_channel_ids;
    // TODO implement heartbeat channel, hasn't been necessary for MVP demo
    // but would be used for host to detect FPGA is crashed and for FPGA to
    // detect host has crashed/gone
    localparam logic [7:0] HEARTBEAT = 8'd1;
    localparam logic [7:0] ADMIN = 8'd2;
    localparam logic [7:0] PROGRAM_ACTIONS = 8'd3;
    localparam logic [7:0] TRIGGER = 8'd4;
endpackage

// AFK wire layouts shared with apps/afk/server/include/afk/fpga/Message.h.
// Packed vectors use MSB-first byte lanes. Multi-byte scalar fields are sent
// little-endian; byteswap functions convert between wire and numeric values.
package afk_message_defines;
    // Full reaction frames fit in an eight-bit byte count.
    localparam int MAX_REACTION_PAYLOAD_SIZE = 237;
    localparam int MAX_REACTION_MESSAGE_SIZE = 255;
    localparam int MAX_CONDITION_MSG_SIZE = 32;

    typedef logic [63:0] cycle_count_t;
    typedef logic [63:0] request_id_t;
    typedef logic [7:0] trigger_id_t;
    typedef logic [7:0] reaction_id_t;
    typedef logic [7:0] condition_id_t;
    typedef logic [MAX_REACTION_PAYLOAD_SIZE-1:0][7:0] reaction_payload_t;
    typedef logic [MAX_CONDITION_MSG_SIZE-1:0][7:0] condition_payload_t;

    // AFK message IDs use the shared application-specific range, leaving the
    // standard echo message IDs available on the same connection.
    localparam fdk_message_defines::msg_hdr_msg_type_t HEARTBEAT_MSG_TYPE =
        fdk_message_defines::APP_SPECIFIC_MSG_TYPE_0;
    localparam fdk_message_defines::msg_hdr_msg_type_t TEST_REQUEST_MSG_TYPE =
        fdk_message_defines::APP_SPECIFIC_MSG_TYPE_1;
    localparam fdk_message_defines::msg_hdr_msg_type_t ACK_MSG_TYPE =
        fdk_message_defines::APP_SPECIFIC_MSG_TYPE_2;
    localparam fdk_message_defines::msg_hdr_msg_type_t PROGRAM_REACTION_MSG_TYPE =
        fdk_message_defines::APP_SPECIFIC_MSG_TYPE_4;
    localparam fdk_message_defines::msg_hdr_msg_type_t PROGRAM_CONDITION_MSG_TYPE =
        fdk_message_defines::APP_SPECIFIC_MSG_TYPE_5;
    localparam fdk_message_defines::msg_hdr_msg_type_t DISABLE_CONDITION_MSG_TYPE =
        fdk_message_defines::APP_SPECIFIC_MSG_TYPE_6;

    typedef struct packed {
        cycle_count_t cycle_count;
    } heartbeat_t;

    // Standalone Reaction header. Exactly reaction_len payload bytes follow.
    typedef struct packed {
        logic [55:0] preamble;
        logic [7:0] start_frame_delimiter;
        request_id_t request_id;
        condition_id_t trigger_condition_id;
        logic [7:0] reaction_len;
    } reaction_header_t;

    // Send the entire payload array, even when reaction_len is shorter.
    typedef struct packed {
        reaction_id_t reaction_id;
        logic [7:0] reaction_len;
        reaction_payload_t payload;
    } program_reaction_t;

    // Send the entire pattern array, even when pattern_len is shorter.
    typedef struct packed {
        condition_id_t condition_id;
        reaction_id_t reaction_id;
        logic [7:0] pattern_len;
        condition_payload_t payload;
    } program_condition_t;

    typedef struct packed {
        condition_id_t condition_id;
    } disable_condition_t;

    localparam logic [55:0] STIMULUS_PREAMBLE = 56'haaaaaaaaaaaaaa;
    localparam logic [7:0] STIMULUS_START_FRAME_DELIMITER = 8'hab;
    localparam logic [63:0] STIMULUS_PREAMBLE_SFD =
        {STIMULUS_PREAMBLE, STIMULUS_START_FRAME_DELIMITER};

    localparam logic [63:0] REACTION_PREAMBLE_SFD = STIMULUS_PREAMBLE_SFD;

    // Standalone frame, without an FDK message header. Exactly length payload
    // bytes follow this fixed header; a flexible array is not part of the type.
    // Unlike the old kiosk framing, length is little-endian on the wire.
    typedef struct packed {
        logic [55:0] preamble;
        logic [7:0] start_frame_delimiter;
        request_id_t request_id;
        logic [15:0] length;
    } stimulus_header_t;

    typedef struct packed {
        fdk_message_defines::msg_header_t msg_hdr;
        heartbeat_t msg;
    } heartbeat_message_t;

    // TestRequest and Ack have no body. Ack uses msg_hdr.ack_seq.
    typedef struct packed {
        fdk_message_defines::msg_header_t msg_hdr;
    } test_request_message_t;

    typedef struct packed {
        fdk_message_defines::msg_header_t msg_hdr;
    } ack_message_t;

    typedef struct packed {
        fdk_message_defines::msg_header_t msg_hdr;
        program_reaction_t msg;
    } program_reaction_message_t;

    typedef struct packed {
        fdk_message_defines::msg_header_t msg_hdr;
        program_condition_t msg;
    } program_condition_message_t;

    typedef struct packed {
        fdk_message_defines::msg_header_t msg_hdr;
        disable_condition_t msg;
    } disable_condition_message_t;

    localparam int HEARTBEAT_MESSAGE_BITS = $bits(heartbeat_message_t);
    localparam int HEARTBEAT_MESSAGE_BYTES = HEARTBEAT_MESSAGE_BITS / 8;
    localparam int TEST_REQUEST_MESSAGE_BITS = $bits(test_request_message_t);
    localparam int TEST_REQUEST_MESSAGE_BYTES = TEST_REQUEST_MESSAGE_BITS / 8;
    localparam int ACK_MESSAGE_BITS = $bits(ack_message_t);
    localparam int ACK_MESSAGE_BYTES = ACK_MESSAGE_BITS / 8;
    localparam int REACTION_HEADER_BITS = $bits(reaction_header_t);
    localparam int REACTION_HEADER_BYTES = REACTION_HEADER_BITS / 8;
    localparam int PROGRAM_REACTION_MESSAGE_BITS = $bits(program_reaction_message_t);
    localparam int PROGRAM_REACTION_MESSAGE_BYTES = PROGRAM_REACTION_MESSAGE_BITS / 8;
    localparam int PROGRAM_CONDITION_MESSAGE_BITS = $bits(program_condition_message_t);
    localparam int PROGRAM_CONDITION_MESSAGE_BYTES = PROGRAM_CONDITION_MESSAGE_BITS / 8;
    localparam int DISABLE_CONDITION_MESSAGE_BITS = $bits(disable_condition_message_t);
    localparam int DISABLE_CONDITION_MESSAGE_BYTES = DISABLE_CONDITION_MESSAGE_BITS / 8;
    localparam int STIMULUS_HEADER_BITS = $bits(stimulus_header_t);
    localparam int STIMULUS_HEADER_BYTES = STIMULUS_HEADER_BITS / 8;

    // Apply these to the body and fdk_message_defines::byteswap_header() to the
    // typed message header. Byte arrays and single-byte fields are unchanged.
    function automatic heartbeat_t byteswap_heartbeat(input heartbeat_t value);
        heartbeat_t swapped;
        swapped.cycle_count = {<<8{value.cycle_count}};
        return swapped;
    endfunction

    function automatic reaction_header_t byteswap_reaction_header(input reaction_header_t value);
        reaction_header_t swapped;
        swapped = value;
        swapped.request_id = {<<8{value.request_id}};
        return swapped;
    endfunction

    // Keep request_id in wire order instead when forwarding it as opaque bytes;
    // decoding then encoding with these helpers also preserves the original ID.
    function automatic stimulus_header_t byteswap_stimulus_header(input stimulus_header_t value);
        stimulus_header_t swapped;
        swapped = value;
        swapped.request_id = {<<8{value.request_id}};
        swapped.length = {<<8{value.length}};
        return swapped;
    endfunction
endpackage

// Internal trigger storage and programming interface; these are not wire types.
package afk_trigger_defines;
    localparam int MAX_CONDITIONS = 8;
    localparam int MAX_REACTIONS = 8;

    typedef struct packed {
        logic enabled;
        logic [7:0] reaction_len;
        afk_message_defines::reaction_payload_t payload;
    } reaction_entry_t;

    typedef struct packed {
        logic enabled;
        afk_message_defines::reaction_id_t reaction_id;
        logic [7:0] pattern_len;
        afk_message_defines::condition_payload_t payload;
    } condition_entry_t;
endpackage
