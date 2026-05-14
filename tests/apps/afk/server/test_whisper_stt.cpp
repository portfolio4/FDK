#include <catch2/catch_all.hpp>

#include <afk/whisper/WhisperSTT.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>

namespace {

std::uint32_t ReadInteger(std::istream& file, unsigned size) {
    std::uint32_t value = 0;
    for (unsigned i = 0; i < size; ++i) {
        const auto byte = file.get();
        REQUIRE(byte != std::char_traits<char>::eof());
        value |= static_cast<std::uint32_t>(byte) << (i * 8);
    }
    return value;
}

// Read the first four seconds of mono PCM16 at 16 kHz, excluding WAV headers.
std::string ReadSpeech() {
    std::ifstream file(AFK_WHISPER_TEST_AUDIO, std::ios::binary);
    REQUIRE(file);
    std::array<char, 4> id;
    file.read(id.data(), id.size());
    REQUIRE(std::string_view(id.data(), id.size()) == "RIFF");
    ReadInteger(file, 4);
    file.read(id.data(), id.size());
    REQUIRE(std::string_view(id.data(), id.size()) == "WAVE");
    bool pcm16 = false;
    while (file.read(id.data(), id.size())) {
        const auto size = ReadInteger(file, 4);
        const std::string_view chunk(id.data(), id.size());
        if (chunk == "fmt ") {
            REQUIRE(size >= 16);
            REQUIRE(ReadInteger(file, 2) == 1); // PCM
            REQUIRE(ReadInteger(file, 2) == 1); // Mono
            REQUIRE(ReadInteger(file, 4) == 16'000);
            ReadInteger(file, 4); // Bytes per second.
            REQUIRE(ReadInteger(file, 2) == 2); // Bytes per sample.
            REQUIRE(ReadInteger(file, 2) == 16);
            file.seekg(size - 16 + size % 2, std::ios::cur);
            pcm16 = true;
        } else if (chunk == "data") {
            REQUIRE(pcm16);
            std::string audio(std::min<std::uint32_t>(size, 4 * 16'000 * 2), '\0');
            file.read(audio.data(), audio.size());
            REQUIRE(file);
            return audio;
        } else {
            file.seekg(size + size % 2, std::ios::cur);
        }
    }
    FAIL("WAV file has no PCM data");
    return {};
}

std::string Lowercase(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return text;
}

} // namespace

using afk::whisper::WhisperSTT;

static_assert(!std::is_copy_constructible_v<WhisperSTT>);
static_assert(!std::is_move_constructible_v<WhisperSTT>);

TEST_CASE("WhisperSTT streams the JFK speech sample", "[afk][whisper][models]") {
    // Load model weights once, but give every section fresh stream state.
    static WhisperSTT stt(AFK_WHISPER_MODEL, AFK_WHISPER_VAD_MODEL);
    stt.reset();
    const auto speech = ReadSpeech();
    const std::string silence(2 * 16'000 * 2, '\0');

    SECTION("Missing resources are rejected") {
        const std::filesystem::path existing_file = __FILE__;
        const auto missing_file = existing_file.parent_path() / "resources/missing-model.bin";
        REQUIRE_THROWS_AS(WhisperSTT(missing_file, existing_file), std::runtime_error);
        REQUIRE_THROWS_AS(WhisperSTT(existing_file, missing_file), std::runtime_error);
    }

    SECTION("Empty input and silence produce no text") {
        const auto empty = stt.stream({});
        REQUIRE(empty);
        CHECK(empty->tentative_text.empty());
        CHECK(empty->committed_text.empty());

        const auto quiet = stt.stream(silence);
        REQUIRE(quiet);
        CHECK(quiet->tentative_text.empty());
        CHECK(quiet->committed_text.empty());

        const auto silent_finish = stt.finish();
        REQUIRE(silent_finish);
        CHECK(silent_finish->committed_text.empty());
    }

    SECTION("Fragmented PCM produces tentative text and commits after silence") {
        const std::array<std::size_t, 3> sizes{1, 511, 3200};
        bool saw_tentative = false;
        std::string committed;
        std::size_t offset = 0;
        for (std::size_t i = 0; offset < speech.size(); ++i) {
            const auto size = std::min(sizes[i % sizes.size()], speech.size() - offset);
            const auto result = stt.stream(std::string_view(speech).substr(offset, size));
            REQUIRE(result);
            offset += size;
            saw_tentative |= !result->tentative_text.empty();
            committed += result->committed_text;
        }

        const auto after_silence = stt.stream(silence);
        REQUIRE(after_silence);
        committed += after_silence->committed_text;
        INFO(committed);
        CHECK(saw_tentative);
        CHECK(Lowercase(committed).find("fellow") != std::string::npos);
        CHECK(after_silence->tentative_text.empty());

        const auto after_commit = stt.finish();
        REQUIRE(after_commit);
        CHECK(after_commit->committed_text.empty());
    }

    SECTION("Reset discards unfinished speech and a partial PCM sample") {
        REQUIRE(stt.stream(std::string_view(speech).substr(0, 32'001)));
        stt.reset();

        const auto after_reset = stt.stream(silence);
        REQUIRE(after_reset);
        CHECK(after_reset->tentative_text.empty());
        CHECK(after_reset->committed_text.empty());

        const auto reset_finish = stt.finish();
        REQUIRE(reset_finish);
        CHECK(reset_finish->committed_text.empty());
    }

    SECTION("Finish commits a final utterance only once") {
        REQUIRE(stt.stream(std::string_view(speech).substr(0, 2 * 16'000 * 2)));
        const auto finished = stt.finish();
        REQUIRE(finished);
        INFO(finished->committed_text);
        CHECK_FALSE(finished->committed_text.empty());
        CHECK(finished->tentative_text.empty());

        const auto repeated = stt.finish();
        REQUIRE(repeated);
        CHECK(repeated->committed_text.empty());
    }
}
