// Single-clock FIFO storing DEPTH words of DATA_WIDTH bits.
// DATA_WIDTH must be positive; DEPTH must be a power of two and at least two.
//
// Transfers occur on rising clk edges when valid && ready. The input producer
// must hold in_valid and in_data stable while in_valid && !in_ready.
// The oldest queued word appears combinationally on out_data and stays stable
// while out_valid && !out_ready. Ignore out_data whenever out_valid is low.
// An enqueue into an empty FIFO becomes visible after the clock edge; there
// is no combinational input-to-output bypass.
//
// ALLOW_ENQUEUE_DEQUEUE_WHEN_FULL permits an enqueue when a simultaneous dequeue
// frees a slot, including when full. Disable it to remove the combinational
// dependency on downstream readiness; a full FIFO then accepts new input on
// the cycle after a dequeue.
//
// rst is synchronous and active high. While asserted, in_ready and out_valid
// are low. A rising clock edge with rst high discards all queued words by
// resetting the counters; the storage array is not cleared.
module fdk_fifo #(
    parameter int DATA_WIDTH,
    parameter int DEPTH,
    parameter bit ALLOW_ENQUEUE_DEQUEUE_WHEN_FULL = 1'b0
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

    // Enqueue at tail, dequeue at head. One extra wrap bit distinguishes
    // full from empty; counters wrap at 2*DEPTH. Truncate to the address bits
    // when indexing the buffer. DEPTH=256 uses nine-bit counters.
    counter_t head_ff;
    counter_t tail_ff;

    logic empty;
    assign empty = (head_ff == tail_ff);

    logic full;
    assign full = ((tail_ff - head_ff) == counter_t'(DEPTH));

    assign out_data = buffer_ff[buffer_index_t'(head_ff)];
    assign out_valid = !rst && !empty;

    logic dequeued;
    assign dequeued = out_ready && out_valid;

    assign in_ready = !rst && (!full || (ALLOW_ENQUEUE_DEQUEUE_WHEN_FULL && dequeued));
    logic enqueued;
    assign enqueued = in_ready && in_valid;

    always_ff @(posedge clk) begin
        if (rst) begin
            head_ff <= '0;
            tail_ff <= '0;
        end else begin
            if (enqueued) begin
                buffer_ff[buffer_index_t'(tail_ff)] <= in_data;
                tail_ff <= tail_ff + 1'b1;
            end
            if (dequeued) begin
                head_ff <= head_ff + 1'b1;
            end
        end
    end
endmodule
