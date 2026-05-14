#include <nlohmann/json.hpp>

#include <iostream>
#include <string>
#include <unistd.h>

using Json = nlohmann::json;

int main(int argc, char* argv[]) {
    try {
        std::string prompt;
        bool stdio = false;

        for (int index = 1; index < argc; ++index) {
            const std::string argument = argv[index];
            if (argument == "--stdio") stdio = true;

            if (argument == "-c" && index + 1 < argc) {
                const std::string config = argv[++index];
                const std::string prefix = "developer_instructions=";

                if (config.starts_with(prefix)) {
                    prompt = Json::parse(config.substr(prefix.size())).get<std::string>();
                }
            }
        }

        if (!stdio || prompt.empty()) return 1;

        // test_codex_process.cpp uses arbitrary test messages to check transport
        // behavior, not messages that an actual Codex process sends.
        std::string line;
        while (std::getline(std::cin, line)) {
            const auto message = Json::parse(line);
            if (!message.contains("id") || !message.contains("method")) continue;

            const auto method = message.at("method").get<std::string>();
            if (method == "test/disconnect") return 0;

            if (method == "test/truncate") {
                std::cout << "unfinished line" << std::flush;
                return 0;
            }

            if (method == "test/raw") {
                std::cout << "not JSON\n" << std::flush;
                continue;
            }

            if (method == "test/coalesce") {
                const auto response = Json{
                    {"id", message["id"]}, {"method", method}, {"result", message.at("params")}
                };
                const auto notification = Json{{"method", method}, {"params", {{"text", "coalesced notification"}}}};
                std::cout << response.dump() << '\n' << notification.dump() << '\n' << std::flush;
                continue;
            }

            Json result = message.value("params", Json::object());
            if (method == "test/prompt") result = prompt;
            if (method == "test/pid") result = ::getpid();

            const auto response = Json{{"id", message["id"]}, {"result", result}}.dump() + '\n';

            std::cout << response << std::flush;
        }
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
