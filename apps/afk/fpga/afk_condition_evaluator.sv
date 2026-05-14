package afk_condition_evaluator_defines;
    // Configuration is a retained valid/ready transaction between frames.
    // enabled=0 disables the condition without changing its pattern.
    typedef struct packed {
        logic valid;
        afk_message_defines::condition_id_t condition_id;
        afk_message_defines::reaction_id_t reaction_id;
        logic enabled;
        logic [7:0] pattern_len;
        afk_message_defines::condition_payload_t pattern;
    } afk_condition_evaluator_config_t;

    // Fire is a single enqueue attempt; a low fire_ready drops this event.
    typedef struct packed {
        logic valid;
        afk_message_defines::reaction_id_t reaction_id;
        afk_message_defines::condition_id_t condition_id;
        afk_message_defines::request_id_t request_id;
    } afk_condition_evaluator_fire_t;
endpackage

// Like the shared message-handler types, stimulus depends on platform width.
// ready travels in the opposite direction and remains a separate port.
`ifndef AFK_CONDITION_EVALUATOR_STIMULUS_T
`define AFK_CONDITION_EVALUATOR_STIMULUS_T(PAYLOAD_BYTES) struct packed { \
    logic valid; \
    logic [(PAYLOAD_BYTES)*8-1:0] data; \
    logic [$clog2((PAYLOAD_BYTES)+1)-1:0] byte_count; \
    logic sop; \
    logic eop; \
    afk_message_defines::request_id_t request_id; \
}
`endif

// Own programmed conditions and evaluate accepted stimulus payload beats.
// Programming is an atomic, already-validated update between frames. The caller
// stages the small raw pattern; only matchers retain persistent pattern copies.
// fire.valid is a one-cycle enqueue ATTEMPT, not a retained output beat:
// if fire_ready is low, the attempt is dropped without stalling the stimulus.
module afk_condition_evaluator #(
    parameter int CHANNEL_PAYLOAD_BYTES = 8,
    parameter int MAX_CONDITIONS = afk_trigger_defines::MAX_CONDITIONS,
    parameter int MAX_REACTIONS = afk_trigger_defines::MAX_REACTIONS,
    parameter type afk_condition_evaluator_stimulus_t =
        `AFK_CONDITION_EVALUATOR_STIMULUS_T(CHANNEL_PAYLOAD_BYTES)
)
(
    input logic clk,
    input logic rst,

    input afk_condition_evaluator_defines::afk_condition_evaluator_config_t in_config,
    output logic config_ready,

    // Live reaction metadata, held constant throughout a stimulus frame by the
    // configuration controller. Reaction payloads never enter this component.
    input logic [MAX_REACTIONS-1:0] reaction_enabled,

    input afk_condition_evaluator_stimulus_t stimulus,
    output logic stimulus_ready,

    output afk_condition_evaluator_defines::afk_condition_evaluator_fire_t fire,
    input logic fire_ready
);
    localparam int PATTERN_BYTES = afk_message_defines::MAX_CONDITION_MSG_SIZE;
    localparam int PATTERN_LENGTH_BITS = $clog2(PATTERN_BYTES + 1);
    localparam int REACTION_INDEX_BITS = MAX_REACTIONS > 1 ? $clog2(MAX_REACTIONS) : 1;

    initial begin
        assert(CHANNEL_PAYLOAD_BYTES > 0)
            else $fatal(1, "Condition evaluator requires positive beat width");
        assert(MAX_CONDITIONS > 0 && MAX_CONDITIONS <= 256 &&
               MAX_REACTIONS > 0 && MAX_REACTIONS <= 256)
            else $fatal(1, "Condition and reaction capacities must fit eight-bit IDs");
    end

    logic [MAX_CONDITIONS-1:0] condition_enabled_ff;
    afk_message_defines::reaction_id_t reaction_id_ff [0:MAX_CONDITIONS-1];
    logic frame_active_ff, frame_fired_ff, clear_history_ff;
    afk_message_defines::request_id_t request_id_ff;
    logic stimulus_accepted, payload_accepted, load_accepted;

    // Stimulus wins simultaneous programming; an active frame includes gaps.
    assign stimulus_ready = !rst && !clear_history_ff;
    assign stimulus_accepted = stimulus.valid && stimulus_ready;
    assign payload_accepted = stimulus_accepted && (frame_active_ff || stimulus.sop);
    assign config_ready = !rst && !frame_active_ff &&
                          !clear_history_ff && !stimulus.valid;
    assign load_accepted = in_config.valid && config_ready;

    afk_message_defines::condition_payload_t aligned_pattern;
    logic [PATTERN_BYTES-1:0] pattern_mask;
    fdk_fast_string_contains_pattern_preparer #(
        .MAX_PATTERN_CHARS(PATTERN_BYTES)
    ) pattern_preparer (
        .pattern(in_config.pattern),
        .pattern_len(PATTERN_LENGTH_BITS'(in_config.pattern_len)),
        .aligned_pattern(aligned_pattern),
        .pattern_mask(pattern_mask)
    );

    logic [MAX_CONDITIONS-1:0] match_valid, is_match;
    for (genvar i = 0; i < MAX_CONDITIONS; i++) begin : conditions
        fdk_fast_string_contains #(
            .INPUT_WIDTH(CHANNEL_PAYLOAD_BYTES*8),
            .MAX_PATTERN_CHARS(PATTERN_BYTES)
        ) matcher (
            .clk(clk),
            .rst(rst || clear_history_ff),
            .aligned_pattern(aligned_pattern),
            .pattern_mask(pattern_mask),
            .load_new_pattern(load_accepted && in_config.enabled && in_config.condition_id == 8'(i)),
            .in_data(stimulus.data),
            .in_byte_count(stimulus.byte_count),
            .in_valid(payload_accepted && stimulus.byte_count != 0 && condition_enabled_ff[i]),
            .in_ready(),
            .out_is_match(is_match[i]),
            .out_valid(match_valid[i]),
            .out_ready(1'b1)
        );
    end

    // Separate string comparison from priority selection to meet timing.
    logic [MAX_CONDITIONS-1:0] condition_matches_ff;
    always_ff @(posedge clk) begin
        if (rst) condition_matches_ff <= '0;
        else condition_matches_ff <= match_valid & is_match;
    end

    logic selected_valid;
    always_comb begin
        selected_valid = 0;
        fire.condition_id = '0;
        fire.reaction_id = '0;
        fire.request_id = request_id_ff;
        for (int i = 0; i < MAX_CONDITIONS; i++) begin
            if (!selected_valid && condition_matches_ff[i] &&
                int'(reaction_id_ff[i]) < MAX_REACTIONS) begin
                if (reaction_enabled[REACTION_INDEX_BITS'(reaction_id_ff[i])]) begin
                    selected_valid = 1;
                    fire.condition_id = afk_message_defines::condition_id_t'(i);
                    fire.reaction_id = reaction_id_ff[i];
                end
            end
        end
    end
    assign fire.valid = !rst && selected_valid && !frame_fired_ff;
    // We do not consider fire_ready. If it is low, this fire is silently dropped
    // and we do not retry or fire again for this stimulus frame.

    always_ff @(posedge clk) begin
        if (rst) begin
            condition_enabled_ff <= '0;
            for (int i = 0; i < MAX_CONDITIONS; i++) reaction_id_ff[i] <= '0;
            frame_active_ff <= 0;
            frame_fired_ff <= 0;
            clear_history_ff <= 0;
            request_id_ff <= '0;
        end else begin
            clear_history_ff <= 0;
            if (clear_history_ff) begin
                frame_fired_ff <= 0;
            end else if (fire.valid) begin
                frame_fired_ff <= 1;
            end

            if (load_accepted) begin
                assert(int'(in_config.condition_id) < MAX_CONDITIONS &&
                       (!in_config.enabled || (int'(in_config.reaction_id) < MAX_REACTIONS &&
                                               int'(in_config.pattern_len) <= PATTERN_BYTES)))
                    else $fatal(1, "Invalid internal condition programming request");
                for (int i = 0; i < MAX_CONDITIONS; i++) begin
                    if (in_config.condition_id == 8'(i)) begin
                        condition_enabled_ff[i] <= in_config.enabled && in_config.pattern_len != 0;
                        reaction_id_ff[i] <= in_config.reaction_id;
                    end
                end
            end

            if (payload_accepted) begin
                assert(stimulus.sop == !frame_active_ff)
                    else $fatal(1, "Stimulus SOP must identify the first payload beat only");
                assert(int'(stimulus.byte_count) <= CHANNEL_PAYLOAD_BYTES &&
                       (stimulus.eop || int'(stimulus.byte_count) == CHANNEL_PAYLOAD_BYTES))
                    else $fatal(1, "Only the final stimulus beat may be partial");
                if (frame_active_ff) begin
                    assert(stimulus.request_id == request_id_ff)
                        else $fatal(1, "Stimulus request ID changed within a frame");
                end else begin
                    request_id_ff <= stimulus.request_id;
                end
                frame_active_ff <= !stimulus.eop;
                // History clears next cycle while the registered EOP match
                // is selected; reject payload and programming in that cycle.
                if (stimulus.eop) begin
                    clear_history_ff <= 1;
                end
            end
        end
    end
endmodule
