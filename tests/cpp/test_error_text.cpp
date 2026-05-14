#include <catch2/catch_all.hpp>

#include <fdk/ErrorText.h>

#include <string>

TEST_CASE("ErrorText starts empty and formats messages", "[core][error_text]") {
    fdk::ErrorText error;
    CHECK(error.text().empty());

    error = fdk::ErrorText::format("Error {}: {:04x}", 7, 42);
    CHECK(error.text() == "Error 7: 002a");
}

TEST_CASE("ErrorText bounds formatted output to 64 characters", "[core][error_text]") {
    fdk::ErrorText error;
    const auto length = GENERATE(63, 64, 65, 4096);
    const std::string message(length, 'x');

    error = fdk::ErrorText::format("{}", message);
    CHECK(error.text() == message.substr(0, 64));

    error = fdk::ErrorText::format("{}", "short");
    CHECK(error.text() == "short");

    error = fdk::ErrorText::format("");
    CHECK(error.text().empty());
}

TEST_CASE("ErrorText truncates output produced by format specifiers", "[core][error_text]") {
    const auto error = fdk::ErrorText::format("{:0100}", 42);
    CHECK(error.text() == std::string(64, '0'));
}
