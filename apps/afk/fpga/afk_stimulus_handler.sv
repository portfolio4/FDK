// Raw stimulus byte stream: preamble/SFD, little-endian request ID and length,
// then exactly length payload bytes. Channel SOP/EOP are not packet boundaries.
// The preamble must start at the first byte of an input beat.
// (Not 100% familiar with ethernet standards, but sounds like there are
// restrictions on where preamble/SFD can be so that hardware doesn't have to
// do some insane combinational search ending at N lanes)
// A beat cannot contain bytes from two packets; bytes after payload EOP are padding.
module afk_stimulus_handler #(
    parameter int CHANNEL_PAYLOAD_BYTES = 8,
    parameter type afk_condition_evaluator_stimulus_t =
        `AFK_CONDITION_EVALUATOR_STIMULUS_T(CHANNEL_PAYLOAD_BYTES)
) (
    input logic clk,
    input logic rst,

    input logic [CHANNEL_PAYLOAD_BYTES*8-1:0] in_data,
    input logic in_valid,
    output logic in_ready,

    output afk_condition_evaluator_stimulus_t out_stimulus,
    input logic stimulus_ready
);
    localparam int IN_DATA_BITS = CHANNEL_PAYLOAD_BYTES*8;
    localparam int IN_DATA_BYTES = IN_DATA_BITS/8;

    localparam int OUT_DATA_BITS = $bits(out_stimulus.data);
    localparam int OUT_DATA_BYTES = OUT_DATA_BITS/8;

    localparam int HEADER_BITS = $bits(afk_message_defines::stimulus_header_t);
    localparam int HEADER_BYTES = HEADER_BITS/8;

    // Hold an incomplete header or payload beat, plus one incoming beat.
    localparam int MAX_BUFFER_COUNT =
        (HEADER_BYTES > OUT_DATA_BYTES ? HEADER_BYTES : OUT_DATA_BYTES) + IN_DATA_BYTES - 1;
    localparam int COMBINED_BUFFER_WIDTH = (MAX_BUFFER_COUNT+1)*8;
    typedef logic [$clog2(MAX_BUFFER_COUNT+1)-1:0] buffer_byte_count_t;

    localparam int BYTE_COUNT_BITS = $bits(out_stimulus.byte_count);
    typedef logic [BYTE_COUNT_BITS-1:0] out_byte_count_t;

    logic [COMBINED_BUFFER_WIDTH-1:0] buffer_ff, buffer_next;
    buffer_byte_count_t buffer_count_ff, buffer_count_next;
    logic processed_stimulus_header_ff, processed_stimulus_header_next;
    afk_message_defines::stimulus_header_t stimulus_header_ff, stimulus_header_next;
    logic [15:0] remaining_ff, remaining_next;
    logic first_payload_ff, first_payload_next;
    afk_condition_evaluator_stimulus_t stimulus_ff, stimulus_next;
    logic output_can_advance;

    initial begin
        assert(IN_DATA_BYTES > 0)
            else $fatal(1, "Stimulus handler requires positive beat width");
        assert(IN_DATA_BYTES == OUT_DATA_BYTES)
            else $fatal(1, "Stimulus input and output beat sizes must match");
        assert(OUT_DATA_BITS > 0 && OUT_DATA_BITS % 8 == 0 &&
               BYTE_COUNT_BITS >= $clog2(OUT_DATA_BYTES+1))
            else $fatal(1, "Stimulus output requires whole bytes and sufficient byte-count width");
    end

    assign output_can_advance = !stimulus_ff.valid || stimulus_ready;
    // Drain complete buffered words and the final fragment before accepting more input.
    assign in_ready = !rst && output_can_advance &&
                      (!processed_stimulus_header_ff ||
                       (buffer_count_ff < buffer_byte_count_t'(OUT_DATA_BYTES) &&
                        16'(buffer_count_ff) < remaining_ff));
    always_comb begin
        out_stimulus = stimulus_ff;
        out_stimulus.valid = !rst && stimulus_ff.valid;
    end

    always_comb begin : parse_beat
        logic [COMBINED_BUFFER_WIDTH-1:0] combined_buffer;
        buffer_byte_count_t combined_buffer_count;
        logic final_payload_beat;
        out_byte_count_t output_bytes;

        combined_buffer = buffer_ff;
        combined_buffer_count = buffer_count_ff;
        final_payload_beat = 0;
        output_bytes = 0;
        processed_stimulus_header_next = processed_stimulus_header_ff;
        stimulus_header_next = stimulus_header_ff;
        remaining_next = remaining_ff;
        first_payload_next = first_payload_ff;
        stimulus_next = stimulus_ff;
        if (output_can_advance) stimulus_next.valid = 0;

        if (in_valid && in_ready) begin
            typedef logic [$clog2(COMBINED_BUFFER_WIDTH)-1:0] buffer_bit_index_t;
            combined_buffer[
                buffer_bit_index_t'(COMBINED_BUFFER_WIDTH-1) -
                (buffer_bit_index_t'(combined_buffer_count) * buffer_bit_index_t'(8))
                -: IN_DATA_BITS
            ] = in_data;
            combined_buffer_count += buffer_byte_count_t'(IN_DATA_BYTES);
        end

        if (!processed_stimulus_header_ff) begin
            if (combined_buffer_count >= buffer_byte_count_t'(HEADER_BYTES)) begin
                stimulus_header_next = afk_message_defines::byteswap_stimulus_header(
                    combined_buffer[COMBINED_BUFFER_WIDTH-1 -: HEADER_BITS]);
                if ({stimulus_header_next.preamble, stimulus_header_next.start_frame_delimiter} == afk_message_defines::STIMULUS_PREAMBLE_SFD) begin
                    processed_stimulus_header_next = 1;
                    combined_buffer <<= HEADER_BITS;
                    combined_buffer_count -= buffer_byte_count_t'(HEADER_BYTES);
                    remaining_next = stimulus_header_next.length;
                    first_payload_next = 1;
                end else begin
                    // Reject this beat-aligned header and try the next one.
                    combined_buffer <<= IN_DATA_BITS;
                    combined_buffer_count -= buffer_byte_count_t'(IN_DATA_BYTES);
                end
            end
        end else begin
            if (output_can_advance) begin
                final_payload_beat = (int'(remaining_ff) <= OUT_DATA_BYTES &&
                                     combined_buffer_count >= buffer_byte_count_t'(remaining_ff));
                if (combined_buffer_count >= buffer_byte_count_t'(OUT_DATA_BYTES) || final_payload_beat) begin
                    output_bytes = final_payload_beat ? out_byte_count_t'(remaining_ff) : out_byte_count_t'(OUT_DATA_BYTES);
                    stimulus_next = '{
                        valid: 1'b1,
                        data: combined_buffer[COMBINED_BUFFER_WIDTH-1 -: OUT_DATA_BITS],
                        byte_count: output_bytes,
                        sop: first_payload_ff,
                        eop: final_payload_beat,
                        request_id: stimulus_header_ff.request_id
                    };
                    combined_buffer <<= OUT_DATA_BITS;
                    combined_buffer_count -= buffer_byte_count_t'(OUT_DATA_BYTES);
                    remaining_next = remaining_ff - 16'(output_bytes);
                    first_payload_next = 0;
                    if (final_payload_beat) begin
                        processed_stimulus_header_next = 0;
                        combined_buffer = '0;
                        combined_buffer_count = 0;
                    end
                end
            end
        end
        buffer_next = combined_buffer;
        buffer_count_next = combined_buffer_count;
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            buffer_ff <= '0;
            buffer_count_ff <= '0;
            processed_stimulus_header_ff <= 0;
            stimulus_header_ff <= '0;
            remaining_ff <= '0;
            first_payload_ff <= 1;
            stimulus_ff <= '0;
        end else begin
            buffer_ff <= buffer_next;
            buffer_count_ff <= buffer_count_next;
            processed_stimulus_header_ff <= processed_stimulus_header_next;
            stimulus_header_ff <= stimulus_header_next;
            remaining_ff <= remaining_next;
            first_payload_ff <= first_payload_next;
            stimulus_ff <= stimulus_next;
        end
    end

    assert property (@(posedge clk) disable iff (rst)
        (out_stimulus.valid && !stimulus_ready) |=> out_stimulus.valid && $stable(out_stimulus));
endmodule
