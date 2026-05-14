// Round-robin arbitration of packets with a single registered output beat.
// Producers must hold valid, data, and EOP stable until accepted.
// Lock selection through input gaps until the selected EOP beat is accepted.
// Pack any downstream metadata, including SOP/EOP, into in_data.
// Synchronous active-high reset discards the buffered beat and packet lock.
module fdk_packet_rr_arbiter #(
    parameter int NUM_INPUTS,
    parameter int DATA_WIDTH
)
(
    input logic clk,
    input logic rst,

    input logic [DATA_WIDTH-1:0] in_data [0:NUM_INPUTS-1],
    input logic [NUM_INPUTS-1:0] in_valid,
    input logic [NUM_INPUTS-1:0] in_eop,
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

    logic last_selected_idx_active_ff;
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
        if (last_selected_idx_active_ff) begin
            selected_idx = last_selected_idx_ff;
            selected_idx_valid = in_valid[selected_idx];
            in_ready[selected_idx] = can_output;
        end else begin
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
    end

    // store internally in register so that out_valid goes to 0 right away
    // when rst is pressed
    logic out_valid_ff;
    assign out_valid = !rst && out_valid_ff;

    always_ff @(posedge clk) begin
        if (rst) begin
            last_selected_idx_active_ff <= 0;
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
                    last_selected_idx_active_ff <= !in_eop[selected_idx];
                    last_selected_idx_ff <= selected_idx;
                end
            end
        end
    end
endmodule

