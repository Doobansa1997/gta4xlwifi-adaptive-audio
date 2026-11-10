#pragma once

#include <array>
#include <cstdint>
#include <dlfcn.h>
#include <fstream>
#include <stdexcept>

namespace sb {
template <size_t N> struct Record { int32_t values[N]; };
using Common = Record<16>;
using Thermal = Record<30>;
using Highpass = Record<3>;
using Filter = Record<17>;
using Legacy = Record<58>;
using Music = Record<58>;
using Amf = Record<33>;
struct Group {
    Highpass highpass;
    Filter filter;
    Legacy legacy;
    Music music[16];
    Amf first;
    Amf second;
};
struct Parameters {
    Common common{};
    Thermal thermal{};
    std::array<Group, 4> groups{};
};
static_assert(sizeof(Parameters) == (46 + 4 * 1072) * 4);
using Configure = void (*)(void*, Common, Thermal,
    Highpass, Filter, Legacy, Music*, Amf, Amf,
    Highpass, Filter, Legacy, Music*, Amf, Amf,
    Highpass, Filter, Legacy, Music*, Amf, Amf,
    Highpass, Filter, Legacy, Music*, Amf, Amf);

template <typename T> T symbol(void* library, const char* name) {
    dlerror();
    void* address = dlsym(library, name);
    const char* error = dlerror();
    if (error || !address) throw std::runtime_error(error ? error : "Null symbol");
    return reinterpret_cast<T>(address);
}

inline Parameters read_parameters(const char* path) {
    std::ifstream input(path, std::ios::binary);
    Parameters parameters;
    if (!input.read(reinterpret_cast<char*>(&parameters), sizeof(parameters)) ||
        input.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("Invalid SoundBooster binary parameter payload");
    return parameters;
}

class Engine {
    void* library_ = nullptr;
    void* object_ = nullptr;
    void (*destroy_)(void*) = nullptr;
    int (*process_)(void*, void*, const void*, int, float) = nullptr;
    void (*clear_)(void*) = nullptr;
public:
    Engine() = default;
    Engine(const Engine&) = delete;
    Engine& operator=(const Engine&) = delete;
    ~Engine() {
        if (object_) destroy_(object_);
        if (library_) dlclose(library_);
    }
    void initialize(const char* path, Parameters& parameters, int mode, int bit_depth = 0) {
        if (library_ || (mode != 1 && mode != 2) || (bit_depth != 0 && bit_depth != 3))
            throw std::runtime_error("Invalid engine initialization");
        library_ = dlopen(path, RTLD_NOW | RTLD_LOCAL);
        if (!library_) throw std::runtime_error(dlerror());
        destroy_ = symbol<void (*)(void*)>(
            library_, "_ZN30SoundBooster_Interface_Factory7DestroyEP25SoundBooster_Interface_IF");
        auto create = symbol<void* (*)(int)>(library_, "_ZN30SoundBooster_Interface_Factory6CreateEi");
        object_ = create(mode);
        if (!object_) throw std::runtime_error("SoundBooster factory returned null");
        auto table = *reinterpret_cast<void***>(object_);
        auto init = reinterpret_cast<int (*)(void*, int)>(table[0]);
        auto rate = reinterpret_cast<int (*)(void*, int)>(table[1]);
        if (init(object_, bit_depth) != 0 || rate(object_, 48000) != 0)
            throw std::runtime_error("SoundBooster initialization failed");
        auto configure = reinterpret_cast<Configure>(table[3]);
        auto& a = parameters.groups[0]; auto& b = parameters.groups[1];
        auto& c = parameters.groups[2]; auto& d = parameters.groups[3];
        configure(object_, parameters.common, parameters.thermal,
            a.highpass, a.filter, a.legacy, a.music, a.first, a.second,
            b.highpass, b.filter, b.legacy, b.music, b.first, b.second,
            c.highpass, c.filter, c.legacy, c.music, c.first, c.second,
            d.highpass, d.filter, d.legacy, d.music, d.first, d.second);
        process_ = reinterpret_cast<int (*)(void*, void*, const void*, int, float)>(table[8]);
        clear_ = reinterpret_cast<void (*)(void*)>(table[7]);
    }
    int process(void* output, const void* input, int frames, float volume) {
        return process_(object_, output, input, frames, volume);
    }
    void clear() { clear_(object_); }
};
}
