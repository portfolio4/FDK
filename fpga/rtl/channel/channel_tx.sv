// Encode fixed channel frames:
//   [channel ID][descriptor: reserved(7:2)=0, EOP(1), SOP(0)][payload]
// Each accepted input is one complete channel frame. Wire bytes and input
// payload lanes are MSB-first. Application lengths and padding are opaque.
//
// Output words may cross frame boundaries. An accepted EOP flushes any final
// partial word; output_byte_count identifies valid MSB-first bytes, and unused
// lanes are zero. Input acceptance pauses while the EOP's buffered bytes drain.
// Without EOP, a partial word waits for subsequent frames.
// Transfers occur on valid && ready. Producers must hold all associated fields
// stable while stalled. Reset discards buffered bytes and pending output.
module fdk_channel_tx #(
    parameter int OUTPUT_BEAT_WIDTH,
    parameter int CHANNEL_PAYLOAD_BYTES
)
(
    input logic clk,
    input logic rst,

    input logic [7:0] in_channel_id,
    input logic in_sop,
    input logic in_eop,
    input logic [CHANNEL_PAYLOAD_BYTES*8-1:0] in_data,
    input logic in_valid,
    output logic in_ready,

    output logic [OUTPUT_BEAT_WIDTH-1:0] out_data,
    output logic [$clog2(OUTPUT_BEAT_WIDTH/8+1)-1:0] output_byte_count,
    output logic out_valid,
    input logic out_ready
);
    localparam int OUTPUT_BYTES = OUTPUT_BEAT_WIDTH / 8;
    localparam int FRAME_BYTES = CHANNEL_PAYLOAD_BYTES + 2;
    localparam int FRAME_BITS = FRAME_BYTES * 8;
    // Enough space for a partial transport word plus one complete frame.
    localparam int BUFFER_BYTES = OUTPUT_BYTES + FRAME_BYTES;
    localparam int BUFFER_BITS = BUFFER_BYTES * 8;
    typedef logic [$clog2(BUFFER_BYTES + 1)-1:0] byte_count_t;

    initial begin
        assert(CHANNEL_PAYLOAD_BYTES > 0)
            else $fatal(1, "CHANNEL_PAYLOAD_BYTES must be positive");
        assert(OUTPUT_BEAT_WIDTH > 0 && OUTPUT_BEAT_WIDTH % 8 == 0)
            else $fatal(1, "OUTPUT_BEAT_WIDTH must be a positive multiple of 8");
    end

    logic [BUFFER_BITS-1:0] buffer_ff;
    byte_count_t buffered_bytes_ff;
    logic [BUFFER_BITS-1:0] combined;
    byte_count_t combined_bytes;
    byte_count_t send_bytes;
    logic flush_pending_ff;
    logic flush_pending;
    logic emit_word;

    assign in_ready = !rst && !flush_pending_ff &&
        buffered_bytes_ff <= byte_count_t'(BUFFER_BYTES - FRAME_BYTES);

    always_comb begin
        combined = buffer_ff;
        combined_bytes = buffered_bytes_ff;
        flush_pending = flush_pending_ff;
        if (in_valid && in_ready) begin
            combined[BUFFER_BITS-1-(int'(buffered_bytes_ff)*8) -: FRAME_BITS] = {
                in_channel_id, 6'b0, in_eop, in_sop, in_data
            };
            combined_bytes = buffered_bytes_ff + byte_count_t'(FRAME_BYTES);
            flush_pending = in_eop;
        end
        send_bytes = combined_bytes < byte_count_t'(OUTPUT_BYTES) ?
            combined_bytes : byte_count_t'(OUTPUT_BYTES);
        emit_word = !rst && (!out_valid || out_ready) &&
            (combined_bytes >= byte_count_t'(OUTPUT_BYTES) || flush_pending);
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            buffer_ff <= '0;
            buffered_bytes_ff <= '0;
            flush_pending_ff <= 0;
            out_data <= '0;
            output_byte_count <= '0;
            out_valid <= 0;
        end else begin
            if (flush_pending) begin
                assert(combined_bytes != 0)
                    else $fatal(1, "Pending flush must have buffered bytes");
            end
            buffer_ff <= emit_word ? combined << (int'(send_bytes)*8) : combined;
            buffered_bytes_ff <= emit_word ?
                combined_bytes - send_bytes : combined_bytes;
            flush_pending_ff <= flush_pending &&
                !(emit_word && send_bytes == combined_bytes);

            if (!out_valid || out_ready) begin
                out_valid <= emit_word;
                if (emit_word) begin
                    out_data <= combined[BUFFER_BITS-1 -: OUTPUT_BEAT_WIDTH];
                    output_byte_count <= $bits(output_byte_count)'(send_bytes);
                end else begin
                    output_byte_count <= '0;
                end
            end
        end
    end

    output_stable_when_stalled:
    assert property (@(posedge clk) disable iff (rst)
        (out_valid && !out_ready) |=> out_valid && $stable({out_data, output_byte_count})
    );
endmodule
