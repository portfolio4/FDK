// Decode one routed channel's message stream. Input beats contain
// CHANNEL_PAYLOAD_BYTES valid MSB-first bytes, including channel padding.
// Strip the fixed little-endian message header and repack the remaining bytes.
// msg_size reports header + payload bytes, excluding channel padding. It is
// metadata only: applications determine meaningful payload lengths and ignore padding.
//
// SOP restarts an unfinished message when accepted. After input EOP, in_ready
// stays low until the final payload transfer. Metadata and payload stay stable
// while stalled. Final output lanes are zero-padded; an empty wire payload emits
// one zero beat with SOP/EOP. Truncated headers and input without SOP are ignored.
module fdk_message_rx #(
    parameter int CHANNEL_PAYLOAD_BYTES
)
(
    input logic clk,
    input logic rst,

    input logic [CHANNEL_PAYLOAD_BYTES*8-1:0] in_data,
    input logic in_sop,
    input logic in_eop,
    input logic in_valid,
    output logic in_ready,

    output fdk_message_defines::msg_hdr_msg_size_t out_msg_size,
    output fdk_message_defines::msg_hdr_seq_t out_seq,
    output fdk_message_defines::msg_hdr_seq_t out_ack_seq,
    output fdk_message_defines::msg_hdr_msg_type_t out_msg_type,
    output logic [CHANNEL_PAYLOAD_BYTES*8-1:0] out_data,
    output logic out_sop,
    output logic out_eop,
    output logic out_valid,
    input logic out_ready
);
    localparam int DATA_BITS = CHANNEL_PAYLOAD_BYTES * 8;
    localparam int HEADER_BYTES = fdk_message_defines::MSG_HEADER_BYTES;
    localparam int HEADER_BITS = fdk_message_defines::MSG_HEADER_BITS;
    localparam int HEADER_BUFFER_BYTES =
        ((HEADER_BYTES + CHANNEL_PAYLOAD_BYTES - 1) / CHANNEL_PAYLOAD_BYTES) * CHANNEL_PAYLOAD_BYTES;
    localparam int HEADER_BUFFER_BITS = HEADER_BUFFER_BYTES * 8;
    localparam int HEADER_BYTES_IN_LAST_BEAT = HEADER_BYTES - (HEADER_BUFFER_BYTES - CHANNEL_PAYLOAD_BYTES);

    typedef logic [HEADER_BUFFER_BITS-1:0] header_buffer_t;
    typedef logic [2*DATA_BITS-1:0] payload_buffer_t;
    typedef logic [$clog2(HEADER_BUFFER_BYTES+1)-1:0] header_count_t;
    typedef logic [$clog2(2*CHANNEL_PAYLOAD_BYTES+1)-1:0] payload_count_t;
    typedef logic [$clog2(CHANNEL_PAYLOAD_BYTES+1)-1:0] beat_count_t;
    typedef enum logic {READ_HEADER, READ_PAYLOAD} state_t;
    typedef struct packed {
        state_t state;
        logic active;
        header_buffer_t header_buffer;
        header_count_t header_bytes;
        fdk_message_defines::msg_header_t header;
        payload_buffer_t payload_buffer;
        payload_count_t payload_bytes;
        logic first_payload;
        logic reached_in_eop;
    } registers_t;

    registers_t registers_ff, registers_next;
    beat_count_t payload_bytes_to_send;

    initial begin
        assert(CHANNEL_PAYLOAD_BYTES > 0)
            else $fatal(1, "CHANNEL_PAYLOAD_BYTES must be positive");
    end

    assign out_msg_size = registers_ff.header.msg_size;
    assign out_seq = registers_ff.header.seq;
    assign out_ack_seq = registers_ff.header.ack_seq;
    assign out_msg_type = registers_ff.header.msg_type;
    assign out_data = registers_ff.payload_buffer[2*DATA_BITS-1 -: DATA_BITS];
    assign out_sop = registers_ff.first_payload;
    assign out_eop = registers_ff.reached_in_eop &&
        int'(registers_ff.payload_bytes) <= CHANNEL_PAYLOAD_BYTES;
    assign out_valid = !rst && registers_ff.active && registers_ff.state == READ_PAYLOAD &&
        (int'(registers_ff.payload_bytes) >= CHANNEL_PAYLOAD_BYTES || registers_ff.reached_in_eop);
    assign payload_bytes_to_send = registers_ff.payload_bytes < payload_count_t'(CHANNEL_PAYLOAD_BYTES) ?
        beat_count_t'(registers_ff.payload_bytes) : beat_count_t'(CHANNEL_PAYLOAD_BYTES);

    always_comb begin
        payload_count_t payload_bytes_after_output;
        payload_bytes_after_output = registers_ff.payload_bytes;
        if (out_valid && out_ready) begin
            payload_bytes_after_output -= payload_count_t'(payload_bytes_to_send);
        end

        in_ready = 0;
        if (!rst && !registers_ff.reached_in_eop) begin
            if (in_sop) begin
                // A restart must not invalidate a stalled output beat.
                in_ready = !out_valid || out_ready;
            end else if (!registers_ff.active) begin
                // Accept and discard input until SOP.
                in_ready = 1;
            end else begin
                case (registers_ff.state)
                    READ_HEADER: in_ready = int'(registers_ff.header_bytes) < HEADER_BYTES;
                    READ_PAYLOAD: in_ready = payload_bytes_after_output <= payload_count_t'(CHANNEL_PAYLOAD_BYTES);
                endcase
            end
        end
    end

    always_comb begin
        int leftover_header_bytes;
        registers_next = registers_ff;
        leftover_header_bytes = 0;

        if (registers_ff.active && registers_ff.state == READ_HEADER) begin
            if (int'(registers_ff.header_bytes) >= HEADER_BYTES) begin
                registers_next.header = fdk_message_defines::byteswap_header(
                    registers_ff.header_buffer[HEADER_BUFFER_BITS-1 -: HEADER_BITS]);
                leftover_header_bytes = int'(registers_ff.header_bytes) - HEADER_BYTES;
                registers_next.payload_buffer = '0;
                // Shift away the header tail. For an exact beat boundary,
                // shift by a full beat so no header bytes become payload.
                registers_next.payload_buffer[2*DATA_BITS-1 -: DATA_BITS] =
                    registers_ff.header_buffer[DATA_BITS-1:0] << (HEADER_BYTES_IN_LAST_BEAT*8);
                registers_next.payload_bytes = payload_count_t'(leftover_header_bytes);
                registers_next.state = READ_PAYLOAD;
            end else if (registers_ff.reached_in_eop) begin
                // EOP before the complete header: discard and wait for SOP.
                registers_next.active = 0;
                registers_next.reached_in_eop = 0;
                registers_next.header_bytes = '0;
            end
        end

        if (out_valid && out_ready) begin
            registers_next.payload_buffer = registers_ff.payload_buffer << (payload_bytes_to_send*8);
            registers_next.payload_bytes -= payload_count_t'(payload_bytes_to_send);
            registers_next.first_payload = 0;
            if (out_eop) begin
                registers_next.state = READ_HEADER;
                registers_next.active = 0;
                registers_next.reached_in_eop = 0;
                registers_next.header_bytes = '0;
            end
        end

        if (in_valid && in_ready) begin
            if (in_sop) begin
                registers_next.state = READ_HEADER;
                registers_next.active = 1;
                registers_next.header_buffer = '0;
                registers_next.header_buffer[HEADER_BUFFER_BITS-1 -: DATA_BITS] = in_data;
                registers_next.header_bytes = header_count_t'(CHANNEL_PAYLOAD_BYTES);
                registers_next.payload_buffer = '0;
                registers_next.payload_bytes = '0;
                registers_next.first_payload = 1;
                registers_next.reached_in_eop = in_eop;
            end else if (registers_ff.active) begin
                if (registers_ff.state == READ_HEADER) begin
                    registers_next.header_buffer[
                        HEADER_BUFFER_BITS-1-int'(registers_ff.header_bytes)*8 -: DATA_BITS
                    ] = in_data;
                    registers_next.header_bytes += header_count_t'(CHANNEL_PAYLOAD_BYTES);
                end else begin
                    registers_next.payload_buffer[
                        2*DATA_BITS-1-int'(registers_next.payload_bytes)*8 -: DATA_BITS
                    ] = in_data;
                    registers_next.payload_bytes += payload_count_t'(CHANNEL_PAYLOAD_BYTES);
                end
                registers_next.reached_in_eop = in_eop;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            registers_ff <= '0;
            registers_ff.state <= READ_HEADER;
            registers_ff.first_payload <= 1;
        end else begin
            registers_ff <= registers_next;
        end
    end

    output_stable_when_stalled:
    assert property (@(posedge clk) disable iff (rst)
        (out_valid && !out_ready) |=> out_valid &&
            $stable({out_msg_size, out_seq, out_ack_seq, out_msg_type, out_data, out_sop, out_eop})
    );
endmodule
