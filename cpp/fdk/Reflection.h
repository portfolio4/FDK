#pragma once

#include <string>
#include <typeinfo>

#if defined(__GNUC__) || defined(__clang__)
#include <cxxabi.h>
#include <cstdlib>
#include <memory>
#endif

namespace fdk {

template <typename T>
std::string runtime_type_name() {
    const char* name = typeid(T).name();
#if defined(__GNUC__) || defined(__clang__)
    int status = 0;
    std::unique_ptr<char, void(*)(void*)> res {
        abi::__cxa_demangle(name, nullptr, nullptr, &status),
        std::free
    };
    return (status == 0) ? res.get() : name;
#else
    return name; // MSVC returns human-readable names by default
#endif
}

} // namespace fdk
