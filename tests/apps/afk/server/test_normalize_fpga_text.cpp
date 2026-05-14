#include <catch2/catch_all.hpp>

#include <afk/util/NormalizedFpgaText.h>

#include <string_view>

TEST_CASE("FPGA text normalization keeps lowercase ASCII letters and digits", "[afk][util]") {
    using namespace std::string_view_literals;
    const auto [input, expected] = GENERATE(table<std::string_view, std::string_view>({
        {"", ""},
        {"abc012xyz", "abc012xyz"},
        {"AZaz09", "azaz09"},
        {"Can I get a Classic Cheeseburger, please?", "canigetaclassiccheeseburgerplease"},
        {" \t\r\n!?-_", ""},
        {"A\0B\xff"sv, "ab"},
        {"caf\xc3\xa9 2", "caf2"},
    }));
    CAPTURE(input);
    CHECK(afk::normalize_fpga_text(input) == expected);
}
