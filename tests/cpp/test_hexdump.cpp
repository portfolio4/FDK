#include <catch2/catch_all.hpp>

#include <fdk/Hexdump.h>

#include <array>
#include <cstddef>
#include <span>
#include <string>

TEST_CASE("Hexdump formats byte rows and printable ASCII", "[core][hexdump]") {
    SECTION("Empty input produces no rows") {
        CHECK(fdk::hexdump({}).empty());
    }

    SECTION("Full rows include offsets and a gap after eight bytes") {
        const auto rows = GENERATE(1, 2);
        std::string text;
        for (int row = 0; row < rows; ++row) {
            text += "0123456789ABCDEF";
        }
        std::string expected =
            "00000000  30 31 32 33 34 35 36 37  38 39 41 42 43 44 45 46  |0123456789ABCDEF|\n";
        if (rows == 2) {
            expected +=
                "00000010  30 31 32 33 34 35 36 37  38 39 41 42 43 44 45 46  |0123456789ABCDEF|\n";
        }
        CHECK(fdk::hexdump(std::as_bytes(std::span{text})) == expected);
    }

    SECTION("Partial rows are padded and nonprintable bytes become dots") {
        const std::array bytes{
            std::byte{0x00}, std::byte{0x1f}, std::byte{0x20},
            std::byte{0x7e}, std::byte{0x7f}, std::byte{0xff},
        };
        CHECK(fdk::hexdump(bytes) ==
              "00000000  00 1f 20 7e 7f ff " + std::string(32, ' ') + "|.. ~..|\n");
    }
}
