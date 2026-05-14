// DEPTH entries of up to DATA_WIDTH bits, streamed in BEAT_WIDTH-bit beats.
// DEPTH must be positive; both widths must be positive multiples of eight.
//
// req_valid && req_ready latches req_addr (< DEPTH) and req_write (1 = write).
// The table locks until the operation's final EOP beat is accepted. Streaming
// starts after request acceptance. The first read beat is registered on the
// request-acceptance edge. Writes replace an entry; reads preserve it and emit
// exactly its stored byte length in order.
//
// Beats transfer on valid && ready; hold valid and payload stable when stalled.
// SOP/EOP mark the first/last beats. data_len counts valid MSB-first bytes;
// non-final beats are full, and total length cannot exceed DATA_WIDTH/8 bytes.
// Unused output lanes are zero. Empty entries use one zero-length SOP/EOP beat.
//
// Synchronous active-high rst aborts operations and clears stored lengths.
// req_ready, in_ready, and out_valid are low during reset.
module fdk_stream_array_table #(
    parameter int DEPTH,
    parameter int DATA_WIDTH,
    parameter int BEAT_WIDTH
)
(
    input logic clk,
    input logic rst,

    input logic req_valid,
    output logic req_ready,
    input logic req_write,
    input logic [$clog2(DEPTH)-1:0] req_addr,

    input logic [BEAT_WIDTH-1:0] in_data,
    input logic [$clog2(BEAT_WIDTH/8+1)-1:0] in_data_len,
    input logic in_sop,
    input logic in_eop,
    input logic in_valid,
    output logic in_ready,

    output logic [BEAT_WIDTH-1:0] out_data,
    output logic [$clog2(BEAT_WIDTH/8+1)-1:0] out_data_len,
    output logic out_sop,
    output logic out_eop,
    output logic out_valid,
    input logic out_ready
);

    initial begin
        assert(DEPTH > 1)
            else $fatal("DEPTH must be at least 2");
        assert(DATA_WIDTH > 0 && DATA_WIDTH % 8 == 0)
            else $fatal("DATA_WIDTH must be a whole number of bytes");
        assert(DATA_WIDTH >= BEAT_WIDTH)
            else $fatal("DATA_WIDTH must be larger than a single input beat");
        assert(BEAT_WIDTH > 0 && BEAT_WIDTH % 8 == 0)
            else $fatal("BEAT_WIDTH must be a whole number of bytes");
    end

    localparam int DATA_BYTES = (DATA_WIDTH / 8);
    localparam int BEAT_BYTES = BEAT_WIDTH / 8;
    localparam int WORDS_PER_ENTRY = (DATA_WIDTH + BEAT_WIDTH - 1) / BEAT_WIDTH;
    localparam int RAM_DEPTH = DEPTH * WORDS_PER_ENTRY;

    typedef logic [$clog2(DEPTH)-1:0] addr_t;
    typedef logic [$clog2(DATA_BYTES+1)-1:0] data_byte_count_t;

    typedef enum {
        IDLE,
        READING,
        READING_DRAIN,
        WRITING
    } state_t;
    state_t state_ff;
    addr_t req_addr_ff;
    logic out_valid_ff;

    // Store complete stream beats so each access addresses a whole RAM word.
    // The final word of an entry may include unused byte lanes.
    (* ram_style = "block" *) logic [BEAT_WIDTH-1:0] data [0:RAM_DEPTH-1];
    data_byte_count_t data_byte_count_ff [0:DEPTH-1];
    data_byte_count_t read_byte_offset_ff;
    logic [BEAT_WIDTH-1:0] ram_read_data_ff;

    // writes always successfully process the input block
    assign in_ready = !rst && (state_ff == WRITING);

    // requests always successfully process in IDLE state
    assign req_ready = !rst && (state_ff == IDLE);

    assign out_valid = !rst && out_valid_ff;

    // Mask invalid lanes after the registered RAM read, including empty reads.
    always_comb begin
        out_data = '0;
        for (int lane = 0; lane < BEAT_BYTES; ++lane) begin
            if (lane < int'(out_data_len)) begin
                out_data[BEAT_WIDTH-1-lane*8 -: 8] = ram_read_data_ff[BEAT_WIDTH-1-lane*8 -: 8];
            end
        end
    end

    data_byte_count_t base_byte_addr;
    data_byte_count_t end_byte_addr;
    always_ff @(posedge clk) begin
        if (rst) begin
            state_ff <= IDLE;
            read_byte_offset_ff <= 0;
            data_byte_count_ff <= '{default: '0};
            req_addr_ff <= 0;
            // Leave the RAM and its direct read-data register unreset.
            out_data_len <= 0;
            out_valid_ff <= 0;
            out_sop <= 0;
            out_eop <= 0;
        end else begin

            // Capture the request; the first read also fetches on this edge.
            if (state_ff == IDLE) begin
                if (req_valid && !req_write) begin
                    // Fetch the first word on request acceptance rather than
                    // waiting for the next cycle in READING.
                    ram_read_data_ff <= data[int'(req_addr)*WORDS_PER_ENTRY];
                    end_byte_addr = data_byte_count_ff[req_addr];
                    out_data_len <= 0;
                    for (int i = 0; i < BEAT_BYTES; ++i) begin
                        if (int'(end_byte_addr) > i) begin
                            out_data_len <= $bits(out_data_len)'(i + 1);
                        end
                    end
                    out_valid_ff <= 1;
                    out_sop <= 1;
                    out_eop <= int'(end_byte_addr) <= BEAT_BYTES;
                    state_ff <= int'(end_byte_addr) <= BEAT_BYTES ? READING_DRAIN : READING;
                    read_byte_offset_ff <= data_byte_count_t'(BEAT_BYTES);
                    req_addr_ff <= req_addr;
                end

                if (req_valid && req_write) begin
                    state_ff <= WRITING;
                    data_byte_count_ff[req_addr] <= 0;
                    req_addr_ff <= req_addr;
                end
            end

            if (state_ff == READING) begin
                if (!out_valid_ff || out_ready) begin
                    base_byte_addr = read_byte_offset_ff;
                    end_byte_addr = data_byte_count_ff[req_addr_ff];
                    ram_read_data_ff <= data[int'(req_addr_ff)*WORDS_PER_ENTRY +
                                             int'(base_byte_addr)/BEAT_BYTES];
                    out_data_len <= 0;
                    for (int i = 0; i < BEAT_BYTES; ++i) begin
                        if (int'(end_byte_addr) - int'(base_byte_addr) > i) begin
                            out_data_len <= $bits(out_data_len)'(i + 1);
                        end
                    end
                    out_valid_ff <= 1;
                    out_sop <= (base_byte_addr == 0);
                    if (int'(end_byte_addr) - int'(base_byte_addr) <= BEAT_BYTES) begin
                        out_eop <= 1;
                        state_ff <= READING_DRAIN;
                    end else begin
                        out_eop <= 0;
                    end
                    read_byte_offset_ff <= read_byte_offset_ff + data_byte_count_t'(BEAT_BYTES);
                end
            end

            if (state_ff == READING_DRAIN) begin
                if (out_valid && out_ready) begin
                    state_ff <= IDLE;
                    out_data_len <= 0;
                    out_valid_ff <= 0;
                    out_sop <= 0;
                    out_eop <= 0;
                end
            end

            if (state_ff == WRITING) begin
                if (in_valid && in_ready) begin
                    base_byte_addr = data_byte_count_ff[req_addr_ff];
                    // Do not write past the entry on a zero-length closing beat.
                    if (int'(base_byte_addr) < DATA_BYTES) begin
                        data[int'(req_addr_ff)*WORDS_PER_ENTRY +
                             int'(base_byte_addr)/BEAT_BYTES] <= in_data;
                    end
                    data_byte_count_ff[req_addr_ff] <= data_byte_count_ff[req_addr_ff] + data_byte_count_t'(in_data_len);
                    if (in_eop) begin
                        state_ff <= IDLE;
                    end
                end
            end
        end
    end
endmodule
