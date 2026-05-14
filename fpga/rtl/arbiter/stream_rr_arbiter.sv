// Round-robin arbitration of one ready/valid transfer at a time.
// Each transfer can carry a complete packed packet; no FIFOs are included.
// Producers must hold valid and data stable until accepted.
// Use a synchronous active-high reset and suppress transfers during reset.
// Hold selection while stalled; advance priority only after a transfer.
// Multi-transfer packets would require an end-of-packet signal and locking
// selection through acceptance of the final transfer.
module fdk_stream_rr_arbiter #(
    parameter int NUM_INPUTS,
    parameter int DATA_WIDTH
)
(
    input logic clk,
    input logic rst,

    input logic [DATA_WIDTH-1:0] in_data [0:NUM_INPUTS-1],
    input logic [NUM_INPUTS-1:0] in_valid,
    output logic [NUM_INPUTS-1:0] in_ready,

    output logic [DATA_WIDTH-1:0] out_data,
    output logic out_valid,
    input logic out_ready
);

    initial begin
        assert(NUM_INPUTS > 1 && (NUM_INPUTS & (NUM_INPUTS - 1)) == 0)
            else $fatal("NUM_INPUTS must at least 2 and a power of 2");
    end

    typedef logic [$clog2(NUM_INPUTS)-1:0] input_index_t;

    input_index_t last_selected_idx_ff;

    logic can_output;
    assign can_output = !rst && (!out_valid || out_ready);

    input_index_t selected_idx;
    logic selected_idx_valid;
    input_index_t candidate_idx;
    always_comb begin
        selected_idx = 0;
        selected_idx_valid = 0;
        candidate_idx = 0;
        in_ready = '0;
        for (int i = 1; i <= NUM_INPUTS; ++i) begin
            candidate_idx = input_index_t'(last_selected_idx_ff + input_index_t'(i));
            if (in_valid[candidate_idx]) begin
                selected_idx = candidate_idx;
                selected_idx_valid = 1;
                in_ready[candidate_idx] = can_output;
                break;
            end
        end
    end

    // store internally in register so that out_valid goes to 0 right away
    // when rst is pressed
    logic out_valid_ff;
    assign out_valid = !rst && out_valid_ff;

    always_ff @(posedge clk) begin
        if (rst) begin
            last_selected_idx_ff <= 0;
            out_data <= '0;
            out_valid_ff <= 0;
        end else begin

            if (can_output) begin

                out_valid_ff <= 0;

                // if we have something to output
                if (selected_idx_valid) begin
                    out_data <= in_data[selected_idx];
                    out_valid_ff <= 1;
                    last_selected_idx_ff <= selected_idx;
                end
            end
        end
    end
endmodule

