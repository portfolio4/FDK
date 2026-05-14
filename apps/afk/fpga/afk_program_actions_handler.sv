// Buffer one programming body, decode it with typed slices, then publish it
// through the destination's ready/valid interface. Ack only after publication.
module afk_program_actions_handler #(
    parameter int CHANNEL_PAYLOAD_BYTES = 8,
    parameter int MAX_CONDITIONS = afk_trigger_defines::MAX_CONDITIONS,
    parameter int MAX_REACTIONS = afk_trigger_defines::MAX_REACTIONS,
    localparam int WORDS_PER_REACTION =
        (afk_message_defines::MAX_REACTION_MESSAGE_SIZE + CHANNEL_PAYLOAD_BYTES-1) / CHANNEL_PAYLOAD_BYTES,
    localparam int WORD_INDEX_BITS = WORDS_PER_REACTION > 1 ? $clog2(WORDS_PER_REACTION) : 1,
    parameter type reaction_table_store_t =
        `AFK_REACTION_TABLE_STORE_T(CHANNEL_PAYLOAD_BYTES, WORD_INDEX_BITS)
) (
    input logic clk,
    input logic rst,
    input logic [CHANNEL_PAYLOAD_BYTES*8-1:0] in_data,
    input logic in_sop, in_eop, in_valid,
    output logic in_ready,

    output afk_condition_evaluator_defines::afk_condition_evaluator_config_t out_condition_evaluator_config,
    input logic condition_evaluator_config_ready,
    output reaction_table_store_t out_reaction_table_store,
    input logic reaction_table_store_ready,

    output logic [CHANNEL_PAYLOAD_BYTES*8-1:0] out_data,
    output logic out_sop, out_eop, out_valid,
    input logic out_ready
);
    localparam int DATA_BITS = CHANNEL_PAYLOAD_BYTES*8;
    localparam int BUFFER_WIDTH =
        (($bits(afk_message_defines::program_reaction_t) + DATA_BITS-1)/DATA_BITS)*DATA_BITS;
    localparam int BUFFER_BYTES = BUFFER_WIDTH/8;
    localparam int REACTION_MESSAGE_WIDTH = WORDS_PER_REACTION*DATA_BITS;
    typedef logic [$clog2(BUFFER_BYTES+1)-1:0] byte_count_t;
    typedef `FDK_MESSAGE_HANDLER_INPUT_BEAT_T(CHANNEL_PAYLOAD_BYTES) input_beat_t;
    typedef enum logic [2:0] {RECEIVE, VALIDATE, PROGRAM_CONDITION, DISABLE_CONDITION, PROGRAM_REACTION, ACK, ACK_DRAIN} state_t;

    state_t state_ff;
    input_beat_t request;
    logic request_ready, ack_ready;
    logic [BUFFER_WIDTH-1:0] buffer_ff, buffer_next;
    byte_count_t received_bytes_ff;
    fdk_message_defines::msg_hdr_msg_size_t size_ff;
    fdk_message_defines::msg_hdr_msg_type_t type_ff;
    fdk_message_defines::msg_hdr_seq_t request_seq_ff, send_seq_ff;
    logic [WORD_INDEX_BITS-1:0] program_reaction_word_index_ff;
    afk_message_defines::program_reaction_t program_reaction;
    afk_message_defines::program_condition_t program_condition;
    afk_message_defines::disable_condition_t disable_condition;
    logic [REACTION_MESSAGE_WIDTH-1:0] padded_reaction_message;

    assign program_reaction = buffer_ff[BUFFER_WIDTH-1 -: $bits(afk_message_defines::program_reaction_t)];
    assign program_condition = buffer_ff[BUFFER_WIDTH-1 -: $bits(afk_message_defines::program_condition_t)];
    assign disable_condition = buffer_ff[BUFFER_WIDTH-1 -: $bits(afk_message_defines::disable_condition_t)];
    afk_message_defines::reaction_header_t reaction_header;
    // Trigger-specific IDs are placeholders until the trigger loader supplies them.
    assign reaction_header = '{
        preamble: afk_message_defines::REACTION_PREAMBLE_SFD[63:8],
        start_frame_delimiter: afk_message_defines::REACTION_PREAMBLE_SFD[7:0],
        request_id: '0, trigger_condition_id: '0,
        reaction_len: program_reaction.reaction_len
    };
    assign padded_reaction_message = {reaction_header, program_reaction.payload,
        {(REACTION_MESSAGE_WIDTH-afk_message_defines::REACTION_HEADER_BITS-
          $bits(afk_message_defines::reaction_payload_t)){1'b0}}};
    assign request_ready = !rst && state_ff == RECEIVE;

    fdk_message_rx #(.CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES)) message_receiver (
        .clk(clk), .rst(rst),
        .in_data(in_data), .in_sop(in_sop), .in_eop(in_eop), .in_valid(in_valid), .in_ready(in_ready),
        .out_msg_size(request.msg_size), .out_seq(request.seq), .out_ack_seq(request.ack_seq),
        .out_msg_type(request.msg_type), .out_data(request.data),
        .out_sop(request.sop), .out_eop(request.eop), .out_valid(request.valid), .out_ready(request_ready)
    );

    always_comb begin
        buffer_next = request.sop ? '0 : buffer_ff;
        // The rounded buffer accepts a whole beat, including final padding.
        if ((request.sop ? 0 : int'(received_bytes_ff)) < BUFFER_BYTES) begin
            buffer_next[BUFFER_WIDTH-1-(request.sop ? 0 : int'(received_bytes_ff))*8 -: DATA_BITS] = request.data;
        end
    end

    always_comb begin
        out_condition_evaluator_config = '0;
        if (state_ff == PROGRAM_CONDITION) begin
            out_condition_evaluator_config.valid = !rst;
            out_condition_evaluator_config.condition_id = program_condition.condition_id;
            out_condition_evaluator_config.reaction_id = program_condition.reaction_id;
            out_condition_evaluator_config.enabled = 1;
            out_condition_evaluator_config.pattern_len = program_condition.pattern_len;
            out_condition_evaluator_config.pattern = program_condition.payload;
        end else if (state_ff == DISABLE_CONDITION) begin
            out_condition_evaluator_config.valid = !rst;
            out_condition_evaluator_config.condition_id = disable_condition.condition_id;
        end

        out_reaction_table_store = '0;
        out_reaction_table_store.valid = !rst && state_ff == PROGRAM_REACTION;
        out_reaction_table_store.reaction_id = program_reaction.reaction_id;
        out_reaction_table_store.reaction_len = 8'(afk_message_defines::REACTION_HEADER_BYTES +
                                                   int'(program_reaction.reaction_len));
        out_reaction_table_store.word_index = program_reaction_word_index_ff;
        out_reaction_table_store.data =
            padded_reaction_message[REACTION_MESSAGE_WIDTH-1-int'(program_reaction_word_index_ff)*DATA_BITS -: DATA_BITS];
    end

    fdk_message_tx #(.CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES)) message_transmitter (
        .clk(clk), .rst(rst),
        .in_seq(send_seq_ff), .in_ack_seq(request_seq_ff),
        .in_msg_size(fdk_message_defines::msg_hdr_msg_size_t'(afk_message_defines::ACK_MESSAGE_BYTES)), .in_msg_type(afk_message_defines::ACK_MSG_TYPE),
        .in_data(DATA_BITS'(0)), .in_data_len(($clog2(CHANNEL_PAYLOAD_BYTES+1))'(0)),
        .in_sop(1'b1), .in_eop(1'b1), .in_valid(!rst && state_ff == ACK), .in_ready(ack_ready),
        .out_data(out_data), .out_sop(out_sop), .out_eop(out_eop), .out_valid(out_valid), .out_ready(out_ready)
    );

    always_ff @(posedge clk) begin
        if (rst) begin
            state_ff <= RECEIVE;
            buffer_ff <= '0;
            received_bytes_ff <= 0;
            size_ff <= 0;
            type_ff <= 0;
            request_seq_ff <= 0;
            send_seq_ff <= 0;
            program_reaction_word_index_ff <= 0;
        end else begin
            case (state_ff)
                RECEIVE: begin
                    if (request.valid) begin
                        buffer_ff <= buffer_next;
                        // Saturate so oversized malformed messages cannot wrap.
                        if (request.sop) begin
                            received_bytes_ff <= byte_count_t'(CHANNEL_PAYLOAD_BYTES);
                            size_ff <= request.msg_size;
                            type_ff <= request.msg_type;
                            request_seq_ff <= request.seq;
                        end else if (int'(received_bytes_ff) + CHANNEL_PAYLOAD_BYTES <= BUFFER_BYTES) begin
                            received_bytes_ff <= received_bytes_ff + byte_count_t'(CHANNEL_PAYLOAD_BYTES);
                        end else begin
                            received_bytes_ff <= byte_count_t'(BUFFER_BYTES);
                        end
                        if (request.eop) begin
                            state_ff <= VALIDATE;
                        end
                    end
                end
                VALIDATE: begin
                    program_reaction_word_index_ff <= 0;
                    state_ff <= RECEIVE; // Invalid/unsupported requests receive no success Ack.
                    if (type_ff == afk_message_defines::PROGRAM_REACTION_MSG_TYPE && int'(size_ff) == afk_message_defines::PROGRAM_REACTION_MESSAGE_BYTES &&
                        int'(received_bytes_ff) + fdk_message_defines::MSG_HEADER_BYTES >= afk_message_defines::PROGRAM_REACTION_MESSAGE_BYTES &&
                        int'(program_reaction.reaction_id) < MAX_REACTIONS &&
                        int'(program_reaction.reaction_len) <= afk_message_defines::MAX_REACTION_PAYLOAD_SIZE) begin
                        state_ff <= PROGRAM_REACTION;
                    end else if (type_ff == afk_message_defines::PROGRAM_CONDITION_MSG_TYPE && int'(size_ff) == afk_message_defines::PROGRAM_CONDITION_MESSAGE_BYTES &&
                        int'(received_bytes_ff) + fdk_message_defines::MSG_HEADER_BYTES >= afk_message_defines::PROGRAM_CONDITION_MESSAGE_BYTES &&
                        int'(program_condition.condition_id) < MAX_CONDITIONS &&
                        int'(program_condition.reaction_id) < MAX_REACTIONS &&
                        int'(program_condition.pattern_len) <= afk_message_defines::MAX_CONDITION_MSG_SIZE) begin
                        state_ff <= PROGRAM_CONDITION;
                    end else if (type_ff == afk_message_defines::DISABLE_CONDITION_MSG_TYPE &&
                                 int'(size_ff) == afk_message_defines::DISABLE_CONDITION_MESSAGE_BYTES &&
                                 int'(received_bytes_ff) + fdk_message_defines::MSG_HEADER_BYTES >= afk_message_defines::DISABLE_CONDITION_MESSAGE_BYTES &&
                                 int'(disable_condition.condition_id) < MAX_CONDITIONS) begin
                        state_ff <= DISABLE_CONDITION;
                    end
                end
                PROGRAM_CONDITION, DISABLE_CONDITION: begin
                    if (condition_evaluator_config_ready) begin
                        state_ff <= ACK;
                    end
                end
                PROGRAM_REACTION: begin
                    if (reaction_table_store_ready) begin
                        if ((int'(program_reaction_word_index_ff) + 1)*CHANNEL_PAYLOAD_BYTES >= afk_message_defines::REACTION_HEADER_BYTES + int'(program_reaction.reaction_len)) begin
                            state_ff <= ACK;
                        end else begin
                            program_reaction_word_index_ff <= program_reaction_word_index_ff + 1'b1;
                        end
                    end
                end
                ACK: begin
                    if (ack_ready) begin
                        state_ff <= ACK_DRAIN;
                    end
                end
                ACK_DRAIN: begin
                    if (out_valid && out_ready && out_eop) begin
                        send_seq_ff <= send_seq_ff + fdk_message_defines::msg_hdr_seq_t'(afk_message_defines::ACK_MESSAGE_BYTES);
                        state_ff <= RECEIVE;
                    end
                end
                default: begin
                    state_ff <= RECEIVE;
                end
            endcase
        end
    end
    assert property (@(posedge clk) disable iff (rst)
        (out_condition_evaluator_config.valid && !condition_evaluator_config_ready) |=> out_condition_evaluator_config.valid && $stable(out_condition_evaluator_config));
    assert property (@(posedge clk) disable iff (rst)
        (out_reaction_table_store.valid && !reaction_table_store_ready) |=> out_reaction_table_store.valid && $stable(out_reaction_table_store));
endmodule
