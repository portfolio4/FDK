// Single-clock FIFO with registered output data and ready/valid handshakes.
// The output is sent to a register to reduce combinational logic strain on timing
module fdk_registered_fifo #(
    parameter int DATA_WIDTH,
    parameter int DEPTH
)
(
    input logic clk,
    input logic rst,

    input logic [DATA_WIDTH-1:0] in_data,
    input logic in_valid,
    output logic in_ready,

    output logic [DATA_WIDTH-1:0] out_data,
    output logic out_valid,
    input logic out_ready
);
    initial begin
        assert(DATA_WIDTH >= 1)
            else $fatal(1, "fifo data width must be at least 1 bit");
        assert(DEPTH >= 2)
            else $fatal(1, "fifo depth must be at least 2");
        assert((DEPTH & (DEPTH-1)) == 0)
            else $fatal(1, "fifo depth must be a power of 2");
    end

    logic [DATA_WIDTH-1:0] buffer_ff [0:DEPTH-1];
    typedef logic[$clog2(DEPTH)-1:0] buffer_index_t;
    localparam int COUNTER_WIDTH = $clog2(DEPTH) + 1;
    typedef logic [COUNTER_WIDTH-1:0] counter_t;

    counter_t head_ff;
    counter_t tail_ff;

    logic empty;
    assign empty = (head_ff == tail_ff);

    logic full;
    assign full = ((tail_ff - head_ff) == counter_t'(DEPTH));

    assign in_ready = !rst && !full;
    logic enqueued;
    assign enqueued = in_ready && in_valid;

    always_ff @(posedge clk) begin
        if (rst) begin
            head_ff <= '0;
            tail_ff <= '0;
            out_data <= '0;
            out_valid <= 0;
        end else begin
            if (enqueued) begin
                buffer_ff[buffer_index_t'(tail_ff)] <= in_data;
                tail_ff <= tail_ff + 1'b1;
            end
            if (!out_valid || out_ready) begin
                out_valid <= !empty;
                if (!empty) begin
                    out_data <= buffer_ff[buffer_index_t'(head_ff)];
                    head_ff <= head_ff + 1'b1;
                end
            end
        end
    end
endmodule
