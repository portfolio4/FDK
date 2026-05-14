// Decode fixed channel frames:
//   [channel ID][descriptor: reserved(7:2), EOP(1), SOP(0)][payload]
// Every input lane is valid; input words may cross frame boundaries.
// Both wire bytes and output payload lanes are MSB-first. Application message
// lengths and final-beat padding are opaque to this module.
//
// Transfers occur on valid && ready. Producers must hold all associated fields
// stable while stalled. Reset discards partial frames and pending output and
// assumes the next input byte starts a new frame; no synchronization scan occurs.
module fdk_channel_rx #(
    parameter int INPUT_BEAT_WIDTH,
    parameter int CHANNEL_PAYLOAD_BYTES
)
(
    input logic clk,
    input logic rst,

    input logic [INPUT_BEAT_WIDTH-1:0] in_data,
    input logic in_valid,
    output logic in_ready,

    output logic [7:0] out_channel_id,
    output logic out_sop,
    output logic out_eop,
    output logic [5:0] out_reserved,
    output logic [CHANNEL_PAYLOAD_BYTES*8-1:0] out_data,
    output logic out_valid,
    input logic out_ready
);
    localparam int INPUT_BYTES = INPUT_BEAT_WIDTH / 8;
    localparam int FRAME_BYTES = CHANNEL_PAYLOAD_BYTES + 2;
    localparam int FRAME_BITS = FRAME_BYTES * 8;
    // Enough space for a partial frame plus one complete transport word.
    localparam int BUFFER_BYTES = FRAME_BYTES + INPUT_BYTES;
    localparam int BUFFER_BITS = BUFFER_BYTES * 8;
    typedef logic [$clog2(BUFFER_BYTES + 1)-1:0] byte_count_t;

    initial begin
        assert(CHANNEL_PAYLOAD_BYTES > 0)
            else $fatal(1, "CHANNEL_PAYLOAD_BYTES must be positive");
        assert(INPUT_BEAT_WIDTH > 0 && INPUT_BEAT_WIDTH % 8 == 0)
            else $fatal(1, "INPUT_BEAT_WIDTH must be a positive multiple of 8");
    end

    logic [BUFFER_BITS-1:0] buffer_ff;
    byte_count_t buffered_bytes_ff;
    logic [BUFFER_BITS-1:0] combined;
    byte_count_t combined_bytes;
    logic emit_frame;

    assign in_ready = !rst && buffered_bytes_ff <= byte_count_t'(BUFFER_BYTES - INPUT_BYTES);

    always_comb begin
        combined = buffer_ff;
        combined_bytes = buffered_bytes_ff;
        if (in_valid && in_ready) begin
            // TODO: Compare synthesis against shift-and-OR insertion.
            // combined = combined | (
            //     {in_data, {(BUFFER_BITS-INPUT_BEAT_WIDTH){1'b0}}}
            //     >> (int'(buffered_bytes_ff) * 8)
            // );
            combined[BUFFER_BITS-1-(int'(buffered_bytes_ff)*8) -: INPUT_BEAT_WIDTH] = in_data;
            combined_bytes = buffered_bytes_ff + byte_count_t'(INPUT_BYTES);
        end
        emit_frame = !rst && (!out_valid || out_ready) &&
            combined_bytes >= byte_count_t'(FRAME_BYTES);
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            buffer_ff <= '0;
            buffered_bytes_ff <= '0;
            out_channel_id <= '0;
            out_sop <= 0;
            out_eop <= 0;
            out_reserved <= '0;
            out_data <= '0;
            out_valid <= 0;
        end else begin
            buffer_ff <= emit_frame ? combined << FRAME_BITS : combined;
            buffered_bytes_ff <= emit_frame ?
                combined_bytes - byte_count_t'(FRAME_BYTES) : combined_bytes;

            if (!out_valid || out_ready) begin
                out_valid <= emit_frame;
                if (emit_frame) begin
                    out_channel_id <= combined[BUFFER_BITS-1 -: 8];
                    {out_reserved, out_eop, out_sop} <= combined[BUFFER_BITS-9 -: 8];
                    out_data <= combined[BUFFER_BITS-17 -: CHANNEL_PAYLOAD_BYTES*8];
                end
            end
        end
    end

    output_stable_when_stalled:
    assert property (@(posedge clk) disable iff (rst)
        (out_valid && !out_ready) |=> out_valid &&
            $stable({out_channel_id, out_sop, out_eop, out_reserved, out_data})
    );
endmodule
