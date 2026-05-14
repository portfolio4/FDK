// Prepend the fixed little-endian message header to a routed payload stream.
// in_msg_size is the entire message size (header + payload), excluding padding,
// and must be known at SOP. It is serialized without checking the payload count.
// Callers must hold in_msg_size/in_seq/in_ack_seq/in_msg_type stable from accepted SOP
// through accepted EOP, including input gaps and backpressure.
// in_data_len counts valid MSB-first bytes
// (0..CHANNEL_PAYLOAD_BYTES); unused input lanes are ignored. Final channel
// output lanes are zero-padded. A zero-byte EOP after all bytes have already
// transferred emits a zero closing frame to carry EOP.
// Input without SOP is discarded. Accepted SOP restarts an unfinished message,
// preserving stalled output. After EOP, drain the message before new input.
module fdk_message_tx #(
    parameter int CHANNEL_PAYLOAD_BYTES
)
(
    input logic clk,
    input logic rst,
    input fdk_message_defines::msg_hdr_msg_size_t in_msg_size,
    input fdk_message_defines::msg_hdr_seq_t in_seq,
    input fdk_message_defines::msg_hdr_seq_t in_ack_seq,
    input fdk_message_defines::msg_hdr_msg_type_t in_msg_type,
    input logic [CHANNEL_PAYLOAD_BYTES*8-1:0] in_data,
    input logic [$clog2(CHANNEL_PAYLOAD_BYTES+1)-1:0] in_data_len,
    input logic in_sop,
    input logic in_eop,
    input logic in_valid,
    output logic in_ready,

    output logic [CHANNEL_PAYLOAD_BYTES*8-1:0] out_data,
    output logic out_sop,
    output logic out_eop,
    output logic out_valid,
    input logic out_ready
);
    localparam int DATA_BITS = CHANNEL_PAYLOAD_BYTES * 8;
    localparam int HEADER_BYTES = fdk_message_defines::MSG_HEADER_BYTES;
    localparam int HEADER_BITS = fdk_message_defines::MSG_HEADER_BITS;
    localparam int BUFFER_BYTES = HEADER_BYTES + CHANNEL_PAYLOAD_BYTES;
    localparam int BUFFER_BITS = BUFFER_BYTES * 8;
    typedef logic [BUFFER_BITS-1:0] out_buffer_t;
    typedef logic [$clog2(BUFFER_BYTES+1)-1:0] buffer_count_t;
    typedef logic [$clog2(CHANNEL_PAYLOAD_BYTES+1)-1:0] beat_count_t;
    typedef struct packed {
        out_buffer_t out_buffer;
        buffer_count_t buffered_bytes;
        logic active;
        logic first_beat;
        logic reached_in_eop;
    } registers_t;

    registers_t registers_ff, registers_next;
    beat_count_t bytes_to_send;

    initial begin
        assert(CHANNEL_PAYLOAD_BYTES > 0)
            else $fatal(1, "CHANNEL_PAYLOAD_BYTES must be positive");
    end

    // The leading beat is the output slot. At SOP it contains header bytes,
    // followed by payload bytes if the header is shorter than a channel beat.
    assign out_data = registers_ff.out_buffer[BUFFER_BITS-1 -: DATA_BITS];
    assign out_valid = !rst && registers_ff.active &&
        (registers_ff.buffered_bytes >= buffer_count_t'(CHANNEL_PAYLOAD_BYTES) || registers_ff.reached_in_eop);
    assign out_sop = registers_ff.first_beat;
    assign out_eop = registers_ff.reached_in_eop &&
        registers_ff.buffered_bytes <= buffer_count_t'(CHANNEL_PAYLOAD_BYTES);
    assign bytes_to_send = registers_ff.buffered_bytes < buffer_count_t'(CHANNEL_PAYLOAD_BYTES) ?
        beat_count_t'(registers_ff.buffered_bytes) : beat_count_t'(CHANNEL_PAYLOAD_BYTES);

    always_comb begin
        buffer_count_t bytes_after_output;
        bytes_after_output = registers_ff.buffered_bytes;
        if (out_valid && out_ready) begin
            bytes_after_output -= buffer_count_t'(bytes_to_send);
        end
        in_ready = 0;
        if (!rst && !registers_ff.reached_in_eop) begin
            if (in_sop) begin
                // Restart only after the current output beat can be accepted.
                in_ready = !out_valid || out_ready;
            end else if (!registers_ff.active) begin
                in_ready = 1;
            end else begin
                in_ready = bytes_after_output <= buffer_count_t'(BUFFER_BYTES) - buffer_count_t'(in_data_len);
                // A zero-byte EOP must not change EOP on a stalled last word.
                if (in_eop && in_data_len == 0 && out_valid && !out_ready &&
                    registers_ff.buffered_bytes <= buffer_count_t'(CHANNEL_PAYLOAD_BYTES)) begin
                    in_ready = 0;
                end
            end
        end
    end

    always_comb begin
        fdk_message_defines::msg_header_t message_header;
        registers_next = registers_ff;
        message_header = '0;
        if (out_valid && out_ready) begin
            registers_next.out_buffer = registers_ff.out_buffer << (bytes_to_send*8);
            registers_next.buffered_bytes -= buffer_count_t'(bytes_to_send);
            registers_next.first_beat = 0;
            if (out_eop) begin
                registers_next.active = 0;
                registers_next.reached_in_eop = 0;
            end
        end
        if (in_valid && in_ready) begin
            if (in_sop) begin
                message_header.msg_size = in_msg_size;
                message_header.seq = in_seq;
                message_header.ack_seq = in_ack_seq;
                message_header.msg_type = in_msg_type;
                registers_next.out_buffer = '0;
                registers_next.out_buffer[BUFFER_BITS-1 -: HEADER_BITS] = fdk_message_defines::byteswap_header(message_header);
                registers_next.buffered_bytes = buffer_count_t'(HEADER_BYTES);
                registers_next.active = 1;
                registers_next.first_beat = 1;
            end
            if (registers_next.active) begin
                for (int i = 0; i < CHANNEL_PAYLOAD_BYTES; i++) begin
                    if (i < int'(in_data_len)) begin
                        registers_next.out_buffer[BUFFER_BITS-1-(int'(registers_next.buffered_bytes)+i)*8 -: 8] =
                            in_data[DATA_BITS-1-i*8 -: 8];
                    end
                end
                registers_next.buffered_bytes += buffer_count_t'(in_data_len);
                registers_next.reached_in_eop = in_eop;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            registers_ff <= '0;
        end else begin
            if (in_valid && in_ready) begin
                assert(int'(in_data_len) <= CHANNEL_PAYLOAD_BYTES)
                    else $fatal(1, "in_data_len exceeds channel payload size");
            end
            registers_ff <= registers_next;
        end
    end

    output_stable_when_stalled:
    assert property (@(posedge clk) disable iff (rst)
        (out_valid && !out_ready) |=> out_valid && $stable({out_data, out_sop, out_eop})
    );
endmodule
