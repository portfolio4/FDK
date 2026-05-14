// Match full input beats against a programmed, right-aligned pattern.
// Pulse load_new_pattern to capture aligned_pattern and pattern_mask before
// searching. Each set mask bit makes the corresponding byte a wildcard.
// rst clears stream history while preserving the programmed pattern.
// Every accepted beat appends all lanes; only the final beat may be partial.
// in_byte_count counts valid MSB-first bytes; unused lanes are zeroed internally.
module fdk_fast_string_contains #(
    parameter int INPUT_WIDTH,
    parameter int MAX_PATTERN_CHARS
)
(
    input logic clk,
    input logic rst,

    input logic [MAX_PATTERN_CHARS*8-1:0] aligned_pattern,
    input logic [MAX_PATTERN_CHARS-1:0] pattern_mask,
    input logic load_new_pattern,

    input logic [INPUT_WIDTH-1:0] in_data,
    input logic [$clog2(INPUT_WIDTH/8+1)-1:0] in_byte_count,
    input logic in_valid,
    output logic in_ready,

    output logic out_is_match,
    output logic out_valid,
    input logic out_ready
);
    initial begin
        assert(INPUT_WIDTH >= 8 && INPUT_WIDTH % 8 == 0)
            else $fatal(1, "INPUT_WIDTH must be a positive whole number of bytes");
        assert(MAX_PATTERN_CHARS >= 1)
            else $fatal(1, "MAX_PATTERN_CHARS must be positive");
    end

    logic [MAX_PATTERN_CHARS*8-1:0] aligned_pattern_ff;
    logic [MAX_PATTERN_CHARS-1:0] pattern_mask_ff;
    // Stream resets preserve the programmed pattern. The caller must load a
    // pattern before the first search and disable searches for empty patterns.
    always_ff @(posedge clk) begin
        if (load_new_pattern) begin
            aligned_pattern_ff <= aligned_pattern;
            pattern_mask_ff <= pattern_mask;
        end
    end

    localparam int INPUT_BYTES = INPUT_WIDTH / 8;
    localparam int MAX_PATTERN_BITS = MAX_PATTERN_CHARS * 8;
    localparam int WINDOW_WIDTH = MAX_PATTERN_BITS + INPUT_WIDTH;
    logic [WINDOW_WIDTH-1:0] window_ff;
    logic [WINDOW_WIDTH-1:0] combined;
    logic [INPUT_WIDTH-1:0] padded_in_data;
    for (genvar lane = 0; lane < INPUT_BYTES; lane++) begin : pad_input
        assign padded_in_data[INPUT_WIDTH-1-lane*8 -: 8] =
            int'(in_byte_count) > lane ? in_data[INPUT_WIDTH-1-lane*8 -: 8] : 8'd0;
    end
    assign combined = {window_ff[MAX_PATTERN_BITS-1:0], padded_in_data};

    // All candidate byte positions are fixed at elaboration.
    logic [INPUT_BYTES-1:0] candidate_match;
    for (genvar lane = 0; lane < INPUT_BYTES; lane++) begin : candidates
        logic [MAX_PATTERN_CHARS-1:0] byte_matches;
        for (genvar i = 0; i < MAX_PATTERN_CHARS; i++) begin : compare_bytes
            assign byte_matches[i] = pattern_mask_ff[i] ||
                combined[(lane+i)*8 +: 8] == aligned_pattern_ff[i*8 +: 8];
        end
        assign candidate_match[lane] = &byte_matches;
    end

    assign out_valid = !rst && in_valid;
    assign out_is_match = out_valid && |candidate_match;
    assign in_ready = !rst && (!out_valid || out_ready);

    always_ff @(posedge clk) begin
        if (rst) begin
            window_ff <= '0;
        end else if (in_valid && in_ready) begin
            window_ff <= combined;
        end
    end
endmodule

// Combinational pattern preparation, shareable on a condition programming path.
// Raw bytes are MSB-first. The result is right-aligned; each mask bit marks
// a zero byte, including padding. A zero-length pattern must be disabled by
// its caller. Pulse the matcher's load_new_pattern to capture these outputs.
module fdk_fast_string_contains_pattern_preparer #(
    parameter int MAX_PATTERN_CHARS
)
(
    input logic [MAX_PATTERN_CHARS*8-1:0] pattern,
    input logic [$clog2(MAX_PATTERN_CHARS+1)-1:0] pattern_len,
    output logic [MAX_PATTERN_CHARS*8-1:0] aligned_pattern,
    output logic [MAX_PATTERN_CHARS-1:0] pattern_mask
);
    initial begin
        assert(MAX_PATTERN_CHARS >= 1)
            else $fatal(1, "MAX_PATTERN_CHARS must be positive");
    end
    assign aligned_pattern = pattern >> ((MAX_PATTERN_CHARS - int'(pattern_len)) * 8);
    for (genvar i = 0; i < MAX_PATTERN_CHARS; i++) begin : wildcard_bytes
        assign pattern_mask[i] = aligned_pattern[i*8 +: 8] == 8'd0;
    end
endmodule
