`ifndef AFK_REACTION_TABLE_TYPES
`define AFK_REACTION_TABLE_TYPES
`define AFK_REACTION_TABLE_STORE_T(PAYLOAD_BYTES, INDEX_BITS) struct packed { \
    logic valid; \
    afk_message_defines::reaction_id_t reaction_id; \
    logic [7:0] reaction_len; \
    logic [(INDEX_BITS)-1:0] word_index; \
    logic [(PAYLOAD_BYTES)*8-1:0] data; \
}
`define AFK_REACTION_TABLE_LOAD_T struct packed { \
    logic valid; \
    afk_message_defines::reaction_id_t reaction_id; \
    afk_message_defines::condition_id_t condition_id; \
    afk_message_defines::request_id_t request_id; \
}
`define AFK_REACTION_TABLE_LOAD_RESULT_T(PAYLOAD_BYTES) struct packed { \
    logic valid; \
    logic sop; \
    logic eop; \
    logic [(PAYLOAD_BYTES)*8-1:0] data; \
}
`endif

// Load/store full reaction messages. Load and store are mutually exclusive
// and subsequent operations must wait for prior ones to fully complete.
// Loads take priority over stores. To be safe, when changing out a
// reaction, you should disable all the conditions referencing that reaction
// first.
//
// TODO: improvement would be to have 2 memory addresses per reaction so that
// you can swap out without having to disable the conditions.
module afk_reaction_table #(
    parameter int CHANNEL_PAYLOAD_BYTES = 8,
    parameter int MAX_REACTIONS = afk_trigger_defines::MAX_REACTIONS,
    localparam int WORDS_PER_REACTION =
        (afk_message_defines::MAX_REACTION_MESSAGE_SIZE + CHANNEL_PAYLOAD_BYTES - 1) / CHANNEL_PAYLOAD_BYTES,
    localparam int WORD_INDEX_BITS = WORDS_PER_REACTION > 1 ? $clog2(WORDS_PER_REACTION) : 1,
    parameter type reaction_table_store_t =
        `AFK_REACTION_TABLE_STORE_T(CHANNEL_PAYLOAD_BYTES, WORD_INDEX_BITS),
    parameter type reaction_table_load_t =
        `AFK_REACTION_TABLE_LOAD_T,
    parameter type reaction_table_load_result_t =
        `AFK_REACTION_TABLE_LOAD_RESULT_T(CHANNEL_PAYLOAD_BYTES)
)
(
    input logic clk,
    input logic rst,

    // Program only the words covering reaction_len, starting at word zero.
    // reaction_len includes preamble and headers and must remain stable with
    // reaction_id on every accepted beat. A zero-length store uses one word.
    input reaction_table_store_t in_store,
    output logic store_ready,

    // Accept one request and stream the entire reaction. load_ready remains low
    // until EOP transfers; requests presented while busy are not retained.
    // The last response is zero-padded. Empty/disabled reactions return one zero beat.
    input reaction_table_load_t in_load,
    output logic load_ready,
    output reaction_table_load_result_t out_load,
    input logic out_load_ready,

    // Small live bitmap for the condition evaluator's eligibility checks.
    output logic [MAX_REACTIONS-1:0] reaction_enabled
);
    localparam int DATA_BITS = CHANNEL_PAYLOAD_BYTES * 8;
    localparam int REQUEST_ID_OFFSET = $bits(afk_message_defines::REACTION_PREAMBLE_SFD)/8;
    localparam int CONDITION_ID_OFFSET = REQUEST_ID_OFFSET + $bits(afk_message_defines::request_id_t)/8;
    localparam int BYTE_COUNT_BITS = $clog2(CHANNEL_PAYLOAD_BYTES+1);

    // fdk_stream_array_table requires at least two entries.
    localparam int TABLE_DEPTH = MAX_REACTIONS > 1 ? MAX_REACTIONS : 2;
    localparam int TABLE_ADDR_BITS = $clog2(TABLE_DEPTH);
    typedef logic [TABLE_ADDR_BITS-1:0] reaction_index_t;

    initial begin
        assert(CHANNEL_PAYLOAD_BYTES > 0)
            else $fatal(1, "Reaction table requires positive beat width");
        assert((CHANNEL_PAYLOAD_BYTES & (CHANNEL_PAYLOAD_BYTES-1)) == 0)
            else $fatal(1, "Reaction table beat size must be a power of two");
        assert(WORDS_PER_REACTION > 1)
            else $fatal(1, "Reaction table implementation assumes more than one word per reaction");
        assert(MAX_REACTIONS > 0 && MAX_REACTIONS <= 256)
            else $fatal(1, "Reaction capacity must fit eight-bit IDs");
    end

    typedef enum logic [1:0] {IDLE, STORING, LOADING} state_t;
    state_t state_ff;
    logic [MAX_REACTIONS-1:0] enabled_ff;
    afk_message_defines::reaction_id_t store_reaction_id_ff;
    logic [7:0] store_len_ff;
    logic [WORD_INDEX_BITS-1:0] store_word_ff;
    afk_message_defines::request_id_t request_id_ff;
    afk_message_defines::condition_id_t condition_id_ff;
    logic [WORD_INDEX_BITS-1:0] load_word_ff;

    logic table_req_valid, table_req_ready, table_req_write;
    reaction_index_t table_req_addr;
    logic table_in_valid, table_in_ready, table_in_eop;
    logic [BYTE_COUNT_BITS-1:0] table_in_len, table_out_len;
    logic [DATA_BITS-1:0] table_out_data;
    logic table_out_valid, table_out_sop, table_out_eop;
    logic store_accepted, load_accepted;
    int remaining_store_bytes;

    always_comb begin
        table_req_valid = 0;
        load_ready = 0;
        store_ready = 0;
        table_in_valid = 0;

        // Loads take priority when both a load and a store are offered.
        if (in_load.valid) begin
            table_req_write = 0;
            table_req_addr = reaction_index_t'(in_load.reaction_id);
        end else begin
            table_req_write = 1;
            table_req_addr = reaction_index_t'(in_store.reaction_id);
        end

        if (!rst) begin
            if (state_ff == IDLE) begin
                table_req_valid = in_load.valid || in_store.valid;
                load_ready = table_req_ready;
            end else if (state_ff == STORING) begin
                // The first store word waits for the table's request handshake.
                store_ready = table_in_ready;
                table_in_valid = in_store.valid;
            end
        end

        remaining_store_bytes = int'(store_len_ff) - int'(store_word_ff)*CHANNEL_PAYLOAD_BYTES;
        table_in_eop = remaining_store_bytes <= CHANNEL_PAYLOAD_BYTES;
        if (remaining_store_bytes <= 0) begin
            table_in_len = '0;
        end else if (remaining_store_bytes < CHANNEL_PAYLOAD_BYTES) begin
            table_in_len = BYTE_COUNT_BITS'(remaining_store_bytes);
        end else begin
            table_in_len = BYTE_COUNT_BITS'(CHANNEL_PAYLOAD_BYTES);
        end
    end

    assign store_accepted = in_store.valid && store_ready;
    assign load_accepted = in_load.valid && load_ready;

    fdk_stream_array_table #(
        .DEPTH(TABLE_DEPTH),
        .DATA_WIDTH(afk_message_defines::MAX_REACTION_MESSAGE_SIZE*8),
        .BEAT_WIDTH(DATA_BITS)
    ) messages (
        .clk(clk), .rst(rst),
        .req_valid(table_req_valid), .req_ready(table_req_ready),
        .req_write(table_req_write), .req_addr(table_req_addr),
        .in_data(in_store.data), .in_data_len(table_in_len),
        .in_sop(store_word_ff == 0), .in_eop(table_in_eop),
        .in_valid(table_in_valid), .in_ready(table_in_ready),
        .out_data(table_out_data), .out_data_len(table_out_len),
        .out_sop(table_out_sop), .out_eop(table_out_eop),
        .out_valid(table_out_valid), .out_ready(out_load_ready)
    );

    assign reaction_enabled = rst ? '0 : enabled_ff;
    assign out_load.valid = table_out_valid;
    assign out_load.sop = table_out_sop;
    assign out_load.eop = table_out_eop;
    afk_message_defines::reaction_header_t wire_header;
    always_comb begin
        wire_header = '0;
        wire_header.request_id = request_id_ff;
        wire_header.trigger_condition_id = condition_id_ff;
        wire_header = afk_message_defines::byteswap_reaction_header(wire_header);
    end
    for (genvar lane = 0; lane < CHANNEL_PAYLOAD_BYTES; lane++) begin : load_lanes
        // Patch only valid bytes; empty entries and final padding stay zero.
        always_comb begin
            out_load.data[DATA_BITS-1-lane*8 -: 8] = table_out_data[DATA_BITS-1-lane*8 -: 8];
            if (lane < int'(table_out_len) &&
                int'(load_word_ff)*CHANNEL_PAYLOAD_BYTES + lane >= REQUEST_ID_OFFSET &&
                int'(load_word_ff)*CHANNEL_PAYLOAD_BYTES + lane <= CONDITION_ID_OFFSET) begin
                out_load.data[DATA_BITS-1-lane*8 -: 8] = wire_header[
                    afk_message_defines::REACTION_HEADER_BITS-1-
                    (int'(load_word_ff)*CHANNEL_PAYLOAD_BYTES+lane)*8 -: 8];
            end
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            state_ff <= IDLE;
            enabled_ff <= '0;
            store_reaction_id_ff <= 0;
            store_len_ff <= 0;
            store_word_ff <= 0;
            request_id_ff <= 0;
            condition_id_ff <= 0;
            load_word_ff <= 0;
        end else begin
            case (state_ff)
                IDLE: begin
                    if (load_accepted) begin
                        assert(int'(in_load.reaction_id) < MAX_REACTIONS)
                            else $fatal(1, "Reaction load parameters are out of range");
                        request_id_ff <= in_load.request_id;
                        condition_id_ff <= in_load.condition_id;
                        load_word_ff <= 0;
                        state_ff <= LOADING;
                    end else if (table_req_valid && table_req_ready && table_req_write) begin
                        assert(int'(in_store.reaction_id) < MAX_REACTIONS &&
                               int'(in_store.reaction_len) <= afk_message_defines::MAX_REACTION_MESSAGE_SIZE &&
                               in_store.word_index == 0)
                            else $fatal(1, "Reaction programming must start at word zero with a valid ID and length");
                        store_reaction_id_ff <= in_store.reaction_id;
                        store_len_ff <= in_store.reaction_len;
                        store_word_ff <= 0;
                        enabled_ff[reaction_index_t'(in_store.reaction_id)] <= 0;
                        state_ff <= STORING;
                    end
                end
                STORING: begin
                    if (store_accepted) begin
                        assert(in_store.reaction_id == store_reaction_id_ff &&
                               in_store.reaction_len == store_len_ff &&
                               in_store.word_index == store_word_ff)
                            else $fatal(1, "Reaction programming requires ordered words with stable ID and length");
                        if (table_in_eop) begin
                            enabled_ff[reaction_index_t'(store_reaction_id_ff)] <= 1;
                            state_ff <= IDLE;
                        end else begin
                            store_word_ff <= store_word_ff + 1'b1;
                        end
                    end
                end
                LOADING: begin
                    if (out_load.valid && out_load_ready) begin
                        if (out_load.eop) begin
                            state_ff <= IDLE;
                        end else begin
                            load_word_ff <= load_word_ff + 1'b1;
                        end
                    end
                end
                default: begin
                    assert(0) else $fatal(1, "Invalid reaction table state");
                end
            endcase
        end
    end

    assert property (@(posedge clk) disable iff (rst)
        (out_load.valid && !out_load_ready) |=> out_load.valid && $stable(out_load));
endmodule
