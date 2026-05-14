#pragma once

#include <chrono>
#include <cstdio>
#include <format>
#include <print>
#include <utility>

namespace fdk::logger {

enum class LogLevel {
    DEBUG = 0,
    INFO = 1,
    WARN = 2,
    ERR = 3,
    CRIT = 4
};

class Logger {
public:
    template <typename... Args>
    static void log(const char* file, int line, LogLevel level,
                    std::format_string<Args...> format, Args&&... args) {
        const auto* level_name = [level] {
            switch (level) {
            case LogLevel::DEBUG:
                return "DEBUG";
            case LogLevel::INFO:
                return "INFO";
            case LogLevel::WARN:
                return "WARN";
            case LogLevel::ERR:
                return "ERR";
            case LogLevel::CRIT:
                return "CRIT";
            }
            return "UNK";
        }();

        const auto now = std::chrono::system_clock::now();
        std::println("[{:%Y-%m-%d %H:%M:%S}] [{}] [{}:{}]: {}", now, level_name, file, line,
                     std::format(format, std::forward<Args>(args)...));
        flush();
    }

    static void flush() {
        std::fflush(stdout);
    }
};

} // namespace fdk::logger

#define LOG_LEVEL(level, format, ...) \
    ::fdk::logger::Logger::log(__FILE_NAME__, __LINE__, level, format __VA_OPT__(,) __VA_ARGS__)
#define LOG_DEBUG(format, ...) \
    LOG_LEVEL(::fdk::logger::LogLevel::DEBUG, format __VA_OPT__(,) __VA_ARGS__)
#define LOG_INFO(format, ...) \
    LOG_LEVEL(::fdk::logger::LogLevel::INFO, format __VA_OPT__(,) __VA_ARGS__)
#define LOG_WARN(format, ...) \
    LOG_LEVEL(::fdk::logger::LogLevel::WARN, format __VA_OPT__(,) __VA_ARGS__)
#define LOG_ERR(format, ...) \
    LOG_LEVEL(::fdk::logger::LogLevel::ERR, format __VA_OPT__(,) __VA_ARGS__)
#define LOG_CRIT(format, ...) \
    LOG_LEVEL(::fdk::logger::LogLevel::CRIT, format __VA_OPT__(,) __VA_ARGS__)
