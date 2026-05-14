module afk_main #(
    parameter int CLK_FREQ_HZ = basys3_constants::CLK_FREQ_HZ,
    parameter int BAUD_RATE = basys3_constants::BAUD_RATE,
    parameter int CHANNEL_PAYLOAD_BYTES = basys3_constants::CHANNEL_PAYLOAD_BYTES
)
(
    input logic clk,
    input logic rst,
    input logic rx,
    output logic tx
);
    localparam int FRAME_BITS = CHANNEL_PAYLOAD_BYTES * 8;
    logic [7:0] request_channel_id, response_channel_id;
    logic [FRAME_BITS-1:0] request_data, response_data;
    logic request_sop, request_eop, request_valid, request_ready;
    logic response_sop, response_eop, response_valid, response_ready;

    fdk_uart_channel_endpoint #(
        .CLK_FREQ_HZ(CLK_FREQ_HZ),
        .BAUD_RATE(BAUD_RATE),
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .FRAME_FIFO_DEPTH(4),
        .RX_FIFO_DEPTH(256)
    ) transport (
        .clk(clk),
        .rst(rst),
        .uart_rx(rx),
        .uart_tx(tx),
        .rx_channel_id(request_channel_id),
        .rx_sop(request_sop),
        .rx_eop(request_eop),
        .rx_reserved(),
        .rx_data(request_data),
        .rx_valid(request_valid),
        .rx_ready(request_ready),
        .tx_channel_id(response_channel_id),
        .tx_sop(response_sop),
        .tx_eop(response_eop),
        .tx_data(response_data),
        .tx_valid(response_valid),
        .tx_ready(response_ready)
    );

    logic admin_input_ready;
    logic [FRAME_BITS-1:0] admin_data;
    logic admin_sop, admin_eop, admin_valid, admin_ready;

    afk_admin_handler #(.CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES)) admin_handler (
        .clk(clk), .rst(rst),
        .in_data(request_data), .in_sop(request_sop), .in_eop(request_eop),
        .in_valid(request_valid && request_channel_id == afk_channel_ids::ADMIN),
        .in_ready(admin_input_ready),
        .out_data(admin_data), .out_sop(admin_sop), .out_eop(admin_eop),
        .out_valid(admin_valid), .out_ready(admin_ready)
    );

    localparam int REACTION_WORDS =
        (afk_message_defines::MAX_REACTION_MESSAGE_SIZE + CHANNEL_PAYLOAD_BYTES-1)/CHANNEL_PAYLOAD_BYTES;
    localparam int REACTION_WORD_INDEX_BITS = REACTION_WORDS > 1 ? $clog2(REACTION_WORDS) : 1;
    typedef `AFK_REACTION_TABLE_STORE_T(CHANNEL_PAYLOAD_BYTES, REACTION_WORD_INDEX_BITS) reaction_table_store_t;
    reaction_table_store_t reaction_table_store;
    logic reaction_table_store_ready;
    afk_condition_evaluator_defines::afk_condition_evaluator_config_t condition_evaluator_config;
    logic condition_evaluator_config_ready;
    logic program_actions_input_ready;
    logic [FRAME_BITS-1:0] program_actions_data;
    logic program_actions_sop, program_actions_eop, program_actions_valid, program_actions_ready;

    afk_program_actions_handler #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .reaction_table_store_t(reaction_table_store_t)
    ) program_actions_handler (
        .clk(clk), .rst(rst),
        .in_data(request_data), .in_sop(request_sop), .in_eop(request_eop),
        .in_valid(request_valid && request_channel_id == afk_channel_ids::PROGRAM_ACTIONS),
        .in_ready(program_actions_input_ready),
        .out_condition_evaluator_config(condition_evaluator_config),
        .condition_evaluator_config_ready(condition_evaluator_config_ready),
        .out_reaction_table_store(reaction_table_store), .reaction_table_store_ready(reaction_table_store_ready),
        .out_data(program_actions_data), .out_sop(program_actions_sop), .out_eop(program_actions_eop),
        .out_valid(program_actions_valid), .out_ready(program_actions_ready)
    );

    typedef `AFK_CONDITION_EVALUATOR_STIMULUS_T(CHANNEL_PAYLOAD_BYTES) stimulus_t;
    stimulus_t stimulus;
    logic stimulus_ready, stimulus_input_ready;

    afk_stimulus_handler #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .afk_condition_evaluator_stimulus_t(stimulus_t)
    ) stimulus_handler (
        .clk(clk), .rst(rst),
        .in_data(request_data),
        .in_valid(request_valid && request_channel_id == afk_channel_ids::TRIGGER),
        .in_ready(stimulus_input_ready),
        .out_stimulus(stimulus), .stimulus_ready(stimulus_ready)
    );

    // Only the addressed handler can accept a frame or apply backpressure.
    // Unsupported channels are discarded.
    always_comb begin
        case (request_channel_id)
            afk_channel_ids::ADMIN: begin
                request_ready = admin_input_ready;
            end
            afk_channel_ids::PROGRAM_ACTIONS: begin
                request_ready = program_actions_input_ready;
            end
            afk_channel_ids::TRIGGER: begin
                request_ready = stimulus_input_ready;
            end
            default: begin
                request_ready = !rst;
            end
        endcase
    end

    logic [afk_trigger_defines::MAX_REACTIONS-1:0] reaction_enabled;
    afk_condition_evaluator_defines::afk_condition_evaluator_fire_t fire;
    logic fire_ready;

    afk_condition_evaluator #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .afk_condition_evaluator_stimulus_t(stimulus_t)
    ) condition_evaluator (
        .clk(clk), .rst(rst),
        .in_config(condition_evaluator_config), .config_ready(condition_evaluator_config_ready),
        .reaction_enabled(reaction_enabled),
        .stimulus(stimulus), .stimulus_ready(stimulus_ready), .fire(fire), .fire_ready(fire_ready)
    );

    // One-cycle timing register breaks the matcher/priority-selection path
    // before the reaction table's metadata lookup and BRAM read enable.
    // Valid and IDs advance together every cycle; busy fires are not retried.
    afk_condition_evaluator_defines::afk_condition_evaluator_fire_t fire_ff;
    always_ff @(posedge clk) begin
        if (rst) fire_ff <= '0;
        else fire_ff <= fire;
    end

    typedef `AFK_REACTION_TABLE_LOAD_T reaction_table_load_t;
    reaction_table_load_t reaction_table_load;
    logic reaction_table_load_ready;
    typedef `AFK_REACTION_TABLE_LOAD_RESULT_T(CHANNEL_PAYLOAD_BYTES) reaction_table_load_result_t;
    reaction_table_load_result_t reaction_table_load_result;
    logic reaction_table_load_result_ready;

    afk_reaction_table #(
        .CHANNEL_PAYLOAD_BYTES(CHANNEL_PAYLOAD_BYTES),
        .reaction_table_store_t(reaction_table_store_t),
        .reaction_table_load_t(reaction_table_load_t),
        .reaction_table_load_result_t(reaction_table_load_result_t)
    ) reaction_table (
        .clk(clk), .rst(rst),
        .in_store(reaction_table_store), .store_ready(reaction_table_store_ready),
        .in_load(reaction_table_load), .load_ready(reaction_table_load_ready),
        .out_load(reaction_table_load_result), .out_load_ready(reaction_table_load_result_ready),
        .reaction_enabled(reaction_enabled)
    );

    // Fires are single attempts: a busy table rejects them without queuing.
    assign reaction_table_load.valid = !rst && fire_ff.valid;
    assign reaction_table_load.reaction_id = fire_ff.reaction_id;
    assign reaction_table_load.condition_id = fire_ff.condition_id;
    assign reaction_table_load.request_id = fire_ff.request_id;
    assign fire_ready = reaction_table_load_ready;

    // Different channels can interleave beats while preserving order within each.
    localparam int RESPONSE_BITS = 8 + 2 + FRAME_BITS;
    logic [RESPONSE_BITS-1:0] arbiter_input [0:3];
    logic [RESPONSE_BITS-1:0] arbiter_output;
    assign arbiter_input[0] = {afk_channel_ids::ADMIN, admin_sop, admin_eop, admin_data};
    assign arbiter_input[1] = {afk_channel_ids::PROGRAM_ACTIONS,
                               program_actions_sop, program_actions_eop, program_actions_data};
    assign arbiter_input[2] = {afk_channel_ids::TRIGGER, reaction_table_load_result.sop,
                               reaction_table_load_result.eop, reaction_table_load_result.data};
    // The arbiter requires a power-of-two input count.
    assign arbiter_input[3] = '0;
    logic unused_arbiter_ready;
    assign {response_channel_id, response_sop, response_eop, response_data} = arbiter_output;
    fdk_stream_rr_arbiter #(.NUM_INPUTS(4), .DATA_WIDTH(RESPONSE_BITS)) response_arbiter (
        .clk(clk), .rst(rst),
        .in_data(arbiter_input), .in_valid({1'b0, reaction_table_load_result.valid, program_actions_valid, admin_valid}),
        .in_ready({unused_arbiter_ready, reaction_table_load_result_ready, program_actions_ready, admin_ready}),
        .out_data(arbiter_output), .out_valid(response_valid), .out_ready(response_ready)
    );
endmodule
