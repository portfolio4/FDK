// fake_codex_process.cpp implements a mock Codex child process that reads JSON
// lines from stdin and writes responses to stdout. Its dummy methods include:
//   test/echo: return the request parameters.
//   test/coalesce: write a response and add an extra dummy notification together as two lines.
//   test/raw: return non-JSON text unchanged by the transport.
//   test/disconnect and test/truncate: exit with no response or an incomplete line.
//   test/prompt and test/pid: return the startup prompt or child process ID.
// These tests launch that mock through CodexProcess and use its known responses
// to check Send and PollResponse framing, ordering, and error handling.

#include <catch2/catch_all.hpp>

#include <afk/codex/CodexProcess.h>
#include <boost/system/system_error.hpp>
#include <nlohmann/json.hpp>

#include <cerrno>
#include <string>
#include <string_view>
#include <sys/wait.h>
#include <thread>
#include <type_traits>

namespace {

using Process = afk::codex::CodexProcess;
using Json = nlohmann::json;

static_assert(!std::is_copy_constructible_v<Process>);
static_assert(!std::is_move_constructible_v<Process>);

std::string request(int id, const std::string& method, const std::string& text = "") {
    return Json{{"id", id}, {"method", method}, {"params", {{"text", text}}}}.dump();
}

std::string next_line(Process& process) {
    while (true) {
        auto result = process.PollResponse();

        INFO((result ? "" : result.error()));
        REQUIRE(result);
        if (*result) return std::move(**result);

        std::this_thread::yield();
    }
}

struct Fixture {
    Process process{"Process API test", AFK_FAKE_CODEX_EXECUTABLE};

    Fixture() { REQUIRE(process.Start()); }
};

void check_reaped(pid_t pid) {
    int status = 0;
    CHECK(::waitpid(pid, &status, WNOHANG) == -1);
    CHECK(errno == ECHILD);
}

}

TEST_CASE("CodexProcess handles stopped and repeated lifecycle operations", "[afk][codex][process]") {
    errno = ERANGE;
    Process process("Process API test", AFK_FAKE_CODEX_EXECUTABLE);

    SECTION("Stopped operations return errors") {
        CHECK_FALSE(process.Send("stopped"));
        CHECK_FALSE(process.PollResponse());
    }

    SECTION("Start and Stop are idempotent") {
        REQUIRE(process.Stop());
        REQUIRE(process.Start());
        REQUIRE(process.Start());

        const auto idle = process.PollResponse();
        REQUIRE(idle);
        CHECK_FALSE(*idle);

        REQUIRE(process.Stop());
        REQUIRE(process.Stop());
    }

    SECTION("Empty requests are rejected before and after Start") {
        const bool started = GENERATE(false, true);
        if (started) REQUIRE(process.Start());

        const auto result = process.Send("");
        REQUIRE_FALSE(result);
        CHECK(result.error() == "Codex request should not be empty.");
    }
}

TEST_CASE_METHOD(Fixture, "CodexProcess returns pipelined replies in order", "[afk][codex][process]") {
    for (const auto id : {1, 2, 3}) {
        REQUIRE(process.Send(request(id, "test/echo", std::to_string(id))));
    }

    for (const auto id : {1, 2, 3}) {
        CAPTURE(id);
        const auto reply = Json::parse(next_line(process));
        CHECK(reply.at("id") == id);
        CHECK(reply.at("result").at("text") == std::to_string(id));
    }
}

TEST_CASE_METHOD(Fixture, "CodexProcess frames outgoing and incoming protocol lines", "[afk][codex][process]") {
    SECTION("Echoes and coalesced replies retain their contents") {
        const auto method = GENERATE("test/echo", "test/coalesce");
        const auto text = GENERATE(std::string{}, std::string{"hello"});

        REQUIRE(process.Send(request(4, method, text)));
        const auto response = Json::parse(next_line(process));
        CHECK(response.at("result").at("text") == text);

        if (std::string_view(method) == "test/coalesce") {
            CHECK(response.at("method") == "test/coalesce");

            const auto notification = Json::parse(next_line(process));
            CHECK(notification.at("method") == "test/coalesce");
            CHECK(notification.at("params").at("text") == "coalesced notification");
        }
    }

    SECTION("Pretty JSON with embedded newlines is sent as one line") {
        const auto text = "line one\nline two";
        const auto pretty = Json::parse(request(5, "test/echo", text)).dump(2);

        REQUIRE(process.Send(pretty));
        CHECK(Json::parse(next_line(process)).at("result").at("text") == text);
    }

    SECTION("Incoming text remains opaque to the transport") {
        REQUIRE(process.Send(request(7, "test/raw")));
        CHECK(next_line(process) == "not JSON");
    }

    SECTION("Invalid multiline input is rejected") {
        const auto text = GENERATE("not\nJSON", "not\rJSON");
        CHECK_FALSE(process.Send(text));
    }
}

TEST_CASE("CodexProcess passes the developer prompt as one spawn argument", "[afk][codex][process]") {
    const std::string prompt = "A prompt with spaces, \"quotes\", and\na newline";
    Process process(prompt, AFK_FAKE_CODEX_EXECUTABLE);
    REQUIRE(process.Start());

    REQUIRE(process.Send(request(1, "test/prompt")));
    CHECK(Json::parse(next_line(process)).at("result") == prompt);
}

TEST_CASE_METHOD(Fixture, "CodexProcess reports read failures and restarts without stale data", "[afk][codex][process]") {
    const auto method = GENERATE("test/disconnect", "test/truncate");
    REQUIRE(process.Send(request(1, method)));
    CHECK_THROWS_AS(next_line(process), boost::system::system_error);

    if (std::string_view(method) == "test/disconnect") {
        CHECK_FALSE(process.Send(request(2, "test/echo")));
    }

    REQUIRE(process.Stop());
    REQUIRE(process.Start());

    REQUIRE(process.Send(request(3, "test/echo", "restarted")));
    const auto reply = Json::parse(next_line(process));
    CHECK(reply.at("id") == 3);
    CHECK(reply.at("result").at("text") == "restarted");
}

TEST_CASE("CodexProcess destruction cleans up its child", "[afk][codex][process]") {
    pid_t pid = -1;

    {
        Process process("Process API test", AFK_FAKE_CODEX_EXECUTABLE);
        REQUIRE(process.Start());
        REQUIRE(process.Send(request(1, "test/pid")));
        pid = Json::parse(next_line(process)).at("result");
    }

    check_reaped(pid);
}
