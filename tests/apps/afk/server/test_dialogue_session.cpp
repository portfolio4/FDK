// Exercise the public session API with explicit time and queued backend replies.
#include <catch2/catch_all.hpp>

#include <afk/dialogue/DialogueSession.h>

#include <deque>
#include <utility>
#include <vector>

namespace {

using namespace afk::dialogue;
using namespace std::chrono_literals;
using Json = nlohmann::json;
using AgentResponse = afk::codex::CodexAgent::Response;

Json Reply(const std::string& text) {
    return {{"messages", {{{"type", "Conversation.addSystemMessage"}, {"msg", text}}}}};
}

const auto retry_reply = Reply("I couldn't process that. Please try again.");

struct Request {
    std::uint64_t request_id;
    std::string text;
};

struct FakeAgent final : AgentBackend {
    std::vector<Request> requests;
    std::deque<AgentResponse> responses;
    bool available = true;
    unsigned discards = 0;

    bool Send(std::uint64_t request_id, const std::string& text) override {
        requests.push_back({request_id, text});
        return available;
    }

    std::optional<AgentResponse> Poll() override {
        if (responses.empty()) {
            return std::nullopt;
        }
        auto response = std::move(responses.front());
        responses.pop_front();
        return response;
    }

    void DiscardPendingResponse() override {
        ++discards;
        responses.clear();
    }
};

struct FakeFpga final : FpgaBackend {
    std::vector<Request> requests;
    std::deque<Reaction> responses;
    bool available = true;

    bool Send(std::uint64_t request_id, const std::string& text) override {
        requests.push_back({request_id, text});
        return available;
    }

    std::optional<Reaction> Poll() override {
        if (responses.empty()) {
            return std::nullopt;
        }
        auto response = std::move(responses.front());
        responses.pop_front();
        return response;
    }
};

struct FakeSpeech final : SpeechBackend {
    struct AudioInput {
        std::string session;
        std::string bytes;
    };
    std::vector<AudioInput> audio;
    std::vector<std::string> resets;
    std::deque<Transcription> transcriptions;

    void Audio(const std::string& session, const std::string& bytes) override {
        audio.push_back({session, bytes});
    }

    std::optional<Transcription> Poll() override {
        if (transcriptions.empty()) {
            return std::nullopt;
        }
        auto transcription = std::move(transcriptions.front());
        transcriptions.pop_front();
        return transcription;
    }

    void Reset(const std::string& session) override { resets.push_back(session); }
};

struct FakeClient final : Client {
    std::vector<Json> received;
    bool closed = false;

    void Send(const std::string& text) override { received.push_back(Json::parse(text)); }
    void Close(std::uint16_t, const std::string&) override { closed = true; }
};

struct Fixture {
    Time now{};
    FakeAgent agent;
    FakeFpga fpga;
    FakeSpeech speech;
    FakeClient client;
    DialogueSession session;

    explicit Fixture(Options options = {}) : session(agent, fpga, speech, options) {
        REQUIRE(session.Open("client", &client));
    }

    void EnqueueRequest(const std::string& text) {
        session.OnText("client", Json{{"type", "request"}, {"text", text}}.dump(), now);
    }

    void EnqueueAgentResponse(std::uint64_t request_id, const std::string& text, bool completed = true) {
        agent.responses.push_back({request_id, text, completed});
    }

    void EnqueueFpgaResponse(std::uint64_t request_id, const std::string& text) {
        fpga.responses.push_back({request_id, text});
    }

    void EnqueueTranscription(Transcription transcription) {
        speech.transcriptions.push_back(std::move(transcription));
    }

    void DoneOrdering() { session.OnText("client", R"({"type":"done_ordering"})", now); }
    void Poll() { session.Poll(now); }
};

} // namespace

TEST_CASE("Dialogue connection lifecycle", "[afk][dialogue]") {
    Fixture f;

    SECTION("Opening initializes speech with the connection token") {
        // note: fixture automatically opens with first client
        CHECK(f.session.CurrentSession() == "client:1");
        REQUIRE(f.speech.resets.size() == 1);
        CHECK(f.speech.resets[0] == "client:1");
    }

    SECTION("A second client is rejected without closing the first") {
        FakeClient other;
        CHECK_FALSE(f.session.Open("other", &other));
        CHECK(other.closed);
        CHECK_FALSE(f.client.closed);
        CHECK(f.session.CurrentSession() == "client:1");
    }

    SECTION("A null client cannot open a session") {
        f.session.Close("client");
        CHECK_FALSE(f.session.Open("other", nullptr));
        CHECK_FALSE(f.session.CurrentSession());
    }

    SECTION("Closing another connection leaves the session open") {
        f.session.Close("other");
        CHECK(f.session.CurrentSession() == "client:1");
    }

    SECTION("Closing the active connection removes the session") {
        f.session.Close("client");
        CHECK_FALSE(f.session.CurrentSession());
        CHECK(f.agent.discards == 1);
    }

    SECTION("Reopening the same connection produces a new speech token") {
        const auto old_token = f.session.CurrentSession();
        f.session.Close("client");
        REQUIRE(f.session.Open("client", &f.client));
        CHECK(f.session.CurrentSession() != old_token);
    }
}

TEST_CASE("Dialogue accepts client text requests", "[afk][dialogue]") {
    Fixture f;

    SECTION("Requests are not sent until Poll is called") {
        f.EnqueueRequest("one burger");
        CHECK(f.agent.requests.empty());
        CHECK(f.fpga.requests.empty());
        f.Poll();
        CHECK(f.agent.requests.size() == 1);
        CHECK(f.fpga.requests.size() == 1);
    }

    SECTION("Both backends receive the same ID and the FPGA receives normalized text") {
        f.EnqueueRequest("One BURGER, please!");
        f.Poll();
        REQUIRE(f.agent.requests.size() == 1);
        REQUIRE(f.fpga.requests.size() == 1);
        CHECK(f.agent.requests[0].request_id == f.fpga.requests[0].request_id);
        CHECK(f.agent.requests[0].text == "One BURGER, please!");
        CHECK(f.fpga.requests[0].text == "oneburgerplease");
    }

    SECTION("Malformed JSON receives a retry message") {
        f.session.OnText("client", "not JSON", f.now);
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == retry_reply);
    }

    SECTION("Unintelligible commands receive a retry message") {
        const auto text = GENERATE("null", "{}", R"({"type":"unknown"})",
                                   R"({"type":"request","text":42})");
        f.session.OnText("client", text, f.now);
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == retry_reply);
    }

    SECTION("Empty requests receive a retry message") {
        f.EnqueueRequest("");
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == retry_reply);
    }

    SECTION("Text from another connection is ignored") {
        f.session.OnText("other", R"({"type":"request","text":"one burger"})", f.now);
        f.Poll();
        CHECK(f.agent.requests.empty());
        CHECK(f.fpga.requests.empty());
    }

    SECTION("The FPGA size limit applies after normalization") {
        const auto size = GENERATE(65535U, 65536U);
        f.EnqueueRequest(std::string(size, 'A') + std::string(100, '!'));
        f.Poll();
        CHECK(f.agent.requests.size() == 1);
        CHECK(f.fpga.requests.size() == (size == 65535 ? 1 : 0));
    }

    SECTION("Failure to send to both backends receives a retry message") {
        f.agent.available = false;
        f.fpga.available = false;
        f.EnqueueRequest("one burger");
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == retry_reply);
    }
}

TEST_CASE("Dialogue selects a response for the active request", "[afk][dialogue]") {
    Fixture f;
    f.EnqueueRequest("one burger");
    f.Poll();
    REQUIRE(f.agent.requests.size() == 1);
    const auto request_id = f.agent.requests[0].request_id;

    SECTION("An agent JSON reply is forwarded without waiting for turn completion") {
        f.EnqueueAgentResponse(request_id, Reply("agent").dump(), false);
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Reply("agent"));
    }

    SECTION("An FPGA JSON reply is forwarded") {
        f.EnqueueFpgaResponse(request_id, Reply("fpga").dump());
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Reply("fpga"));
    }

    SECTION("The agent wins when both replies are ready in the same poll") {
        f.EnqueueAgentResponse(request_id, Reply("agent").dump());
        f.EnqueueFpgaResponse(request_id, Reply("fpga").dump());
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Reply("agent"));
    }

    SECTION("A late agent reply is dropped after the FPGA wins") {
        f.EnqueueFpgaResponse(request_id, Reply("fpga").dump());
        f.Poll();
        f.EnqueueAgentResponse(request_id, Reply("late agent").dump());
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Reply("fpga"));
    }

    SECTION("A late FPGA reply is dropped after the agent wins") {
        f.EnqueueAgentResponse(request_id, Reply("agent").dump());
        f.Poll();
        f.EnqueueFpgaResponse(request_id, Reply("late fpga").dump());
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Reply("agent"));
    }

    SECTION("An agent reply with another request ID is dropped") {
        f.EnqueueAgentResponse(request_id + 1, Reply("wrong request").dump());
        f.Poll();
        CHECK(f.client.received.empty());
    }

    SECTION("An FPGA reply with another request ID is dropped") {
        f.EnqueueFpgaResponse(request_id + 1, Reply("wrong request").dump());
        f.Poll();
        CHECK(f.client.received.empty());
    }

    SECTION("An empty agent completion event is ignored") {
        f.EnqueueAgentResponse(request_id, "");
        f.Poll();
        CHECK(f.client.received.empty());
    }

    SECTION("Malformed backend replies leave the other backend eligible") {
        const auto invalid = GENERATE("not JSON", "null", "{}", R"({"messages":1})",
                                      R"({"messages":[null]})", R"({"messages":[{"type":1}]})");
        f.EnqueueAgentResponse(request_id, invalid);
        f.Poll();
        CHECK(f.client.received.empty());
        f.EnqueueFpgaResponse(request_id, Reply("fpga").dump());
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Reply("fpga"));
    }

    SECTION("Replying discards the agent's pending response") {
        f.EnqueueFpgaResponse(request_id, Reply("fpga").dump());
        f.Poll();
        CHECK(f.agent.discards == 1);
    }

    SECTION("Backend message fields are forwarded unchanged") {
        const Json response = {{"messages", {{{"type", "custom"}, {"quantity", 0}, {"extra", nullptr}}}}};
        f.EnqueueAgentResponse(request_id, response.dump());
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == response);
    }
}

TEST_CASE("Dialogue processes queued requests", "[afk][dialogue]") {
    Fixture f(Options{.max_queued_requests = 2});
    f.EnqueueRequest("first");
    f.Poll();
    REQUIRE(f.agent.requests.size() == 1);
    const auto request_id = f.agent.requests[0].request_id;
    f.EnqueueRequest("second");
    f.EnqueueRequest("third");

    SECTION("Queued requests wait indefinitely when neither backend replies") {
        f.now += 24h;
        f.Poll();
        CHECK(f.agent.requests.size() == 1);
        CHECK(f.fpga.requests.size() == 1);
        CHECK(f.client.received.empty());
    }

    SECTION("An agent winner releases the next request in FIFO order") {
        f.EnqueueAgentResponse(request_id, Reply("agent").dump());
        f.Poll();
        REQUIRE(f.agent.requests.size() == 2);
        CHECK(f.agent.requests[1].text == "second");
    }

    SECTION("An FPGA winner releases the next request without waiting for the agent") {
        f.EnqueueFpgaResponse(request_id, Reply("fpga").dump());
        f.Poll();
        REQUIRE(f.agent.requests.size() == 2);
        CHECK(f.agent.requests[1].text == "second");
    }

    SECTION("A full queue rejects additional requests") {
        f.EnqueueRequest("fourth");
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == retry_reply);
    }

    SECTION("A previous request's response cannot reply to the next request") {
        f.EnqueueFpgaResponse(request_id, Reply("first reply").dump());
        f.Poll();
        REQUIRE(f.agent.requests.size() == 2);
        CHECK(f.agent.requests[1].request_id != request_id);
        f.EnqueueAgentResponse(request_id, Reply("late first reply").dump());
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Reply("first reply"));
    }
}

TEST_CASE("Dialogue handles speech input", "[afk][dialogue]") {
    Fixture f(Options{.pause_interval = 2s});
    const auto token = *f.session.CurrentSession();

    SECTION("Audio is forwarded with the current token") {
        f.session.OnAudio("client", "audio bytes");
        REQUIRE(f.speech.audio.size() == 1);
        CHECK(f.speech.audio[0].session == token);
        CHECK(f.speech.audio[0].bytes == "audio bytes");
    }

    SECTION("Audio from another connection is ignored") {
        f.session.OnAudio("other", "audio bytes");
        CHECK(f.speech.audio.empty());
    }

    SECTION("Transcriptions are not processed until Poll is called") {
        f.EnqueueTranscription({token, {}, "one burger"});
        CHECK(f.client.received.empty());
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0]["messages"][0]["msg"] == "one burger");
    }

    SECTION("Committed transcription chunks are joined in the pending preview") {
        f.EnqueueTranscription({token, {}, "one"});
        f.Poll();
        f.EnqueueTranscription({token, {}, "burger"});
        f.Poll();
        REQUIRE(f.client.received.size() == 2);
        CHECK(f.client.received.back() == Json{{"messages", {{{"type", "Conversation.setPendingUserMessage"},
                                                             {"msg", "one burger"}}}}});
    }

    SECTION("Tentative speech is previewed without becoming a request") {
        f.EnqueueTranscription({token, "one burger", {}});
        f.Poll();
        f.now += 2s;
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0]["messages"][0]["msg"] == "one burger");
        CHECK(f.agent.requests.empty());
    }

    SECTION("Each committed chunk restarts the pause interval") {
        f.EnqueueTranscription({token, {}, "one"});
        f.Poll();
        f.now += 1s;
        f.EnqueueTranscription({token, {}, "burger"});
        f.Poll();
        f.now += 1s;
        f.Poll();
        CHECK(f.agent.requests.empty());
        f.now += 1s;
        f.Poll();
        REQUIRE(f.agent.requests.size() == 1);
        CHECK(f.agent.requests[0].text == "one burger");
        CHECK(f.client.received.back() == Json{{"messages", {{{"type", "Conversation.commitPendingUserMessage"}}}}});
    }

    SECTION("Empty transcriptions produce no preview") {
        f.EnqueueTranscription({token, {}, {}});
        f.Poll();
        CHECK(f.client.received.empty());
    }
}

TEST_CASE("Dialogue resets on done_ordering", "[afk][dialogue]") {
    Fixture f;
    const auto token = *f.session.CurrentSession();
    f.EnqueueRequest("active");
    f.Poll();
    REQUIRE(f.agent.requests.size() == 1);
    const auto request_id = f.agent.requests[0].request_id;

    SECTION("The active request is discarded so a new request can start") {
        f.DoneOrdering();
        f.EnqueueRequest("fresh");
        f.Poll();
        REQUIRE(f.agent.requests.size() == 3);
        CHECK(f.agent.requests[2].text == "fresh");
        CHECK(f.agent.requests[2].request_id != f.agent.requests[1].request_id);
    }

    SECTION("The original handoff prompt is sent and its response discarded") {
        f.DoneOrdering();
        REQUIRE(f.agent.requests.size() == 2);
        CHECK(f.agent.requests[1].text ==
              "the current customer is done. a new customer will arrive shortly. no response is required for this.");
        CHECK(f.agent.requests[1].request_id != request_id);
        CHECK(f.fpga.requests.size() == 1); // The handoff is agent-only.
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Json{{"messages", {{{"type", "Cart.clear"}}}}});
    }

    SECTION("Consecutive handoffs use distinct IDs and allow the next customer request") {
        f.DoneOrdering();
        f.DoneOrdering();
        f.EnqueueRequest("next customer");
        f.Poll();
        REQUIRE(f.agent.requests.size() == 4);
        CHECK(f.agent.requests[1].request_id != f.agent.requests[2].request_id);
        CHECK(f.agent.requests[2].request_id != f.agent.requests[3].request_id);
        CHECK(f.agent.requests[3].text == "next customer");
        CHECK(f.fpga.requests.size() == 2); // Only the customer requests.
    }

    SECTION("A late handoff reply cannot modify the next customer's order") {
        f.DoneOrdering();
        const auto handoff_id = f.agent.requests.back().request_id;
        f.EnqueueRequest("fresh");
        f.Poll();
        f.EnqueueAgentResponse(handoff_id, R"({"messages":[{"type":"Cart.clear"}]})");
        f.Poll();
        REQUIRE(f.client.received.size() == 1); // Only the explicit Done Ordering clear.
        f.EnqueueAgentResponse(f.agent.requests.back().request_id, Reply("fresh reply").dump());
        f.Poll();
        REQUIRE(f.client.received.size() == 2);
        CHECK(f.client.received.back() == Reply("fresh reply"));
    }

    SECTION("Queued requests are cleared") {
        f.EnqueueRequest("queued");
        f.DoneOrdering();
        f.Poll();
        CHECK(f.agent.requests.size() == 2); // Active request plus handoff, no queued request.
    }

    SECTION("Unsubmitted speech is cleared") {
        f.EnqueueTranscription({token, {}, "unsubmitted"});
        f.Poll();
        f.DoneOrdering();
        f.now += 3s;
        f.Poll();
        CHECK(f.agent.requests.size() == 2); // Active request plus handoff, no speech request.
        CHECK(f.client.received.size() == 2); // Original preview and cart reset.
    }

    SECTION("Speech is reset with a new token") {
        f.DoneOrdering();
        CHECK(f.session.CurrentSession() != token);
        REQUIRE(f.speech.resets.size() == 2);
        CHECK(f.speech.resets.back() == *f.session.CurrentSession());
    }

    SECTION("Late agent replies cannot reply to a request started after reset") {
        f.DoneOrdering();
        f.EnqueueRequest("fresh");
        f.Poll();
        REQUIRE(f.agent.requests.size() == 3);
        f.EnqueueAgentResponse(request_id, Reply("old agent reply").dump());
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Json{{"messages", {{{"type", "Cart.clear"}}}}});
    }

    SECTION("Late FPGA replies cannot reply to a request started after reset") {
        f.DoneOrdering();
        f.EnqueueRequest("fresh");
        f.Poll();
        REQUIRE(f.agent.requests.size() == 3);
        f.EnqueueFpgaResponse(request_id, Reply("old fpga reply").dump());
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Json{{"messages", {{{"type", "Cart.clear"}}}}});
    }

    SECTION("Transcriptions using the previous token are ignored") {
        f.DoneOrdering();
        f.EnqueueTranscription({token, {}, "old speech"});
        f.Poll();
        REQUIRE(f.client.received.size() == 1);
        CHECK(f.client.received[0] == Json{{"messages", {{{"type", "Cart.clear"}}}}});
    }

    SECTION("An agent reply cannot reset the conversation") {
        f.EnqueueAgentResponse(request_id, Reply("Your order is complete.").dump());
        f.Poll();
        CHECK(f.session.CurrentSession() == token);
        CHECK(f.speech.resets.size() == 1);
    }
}
