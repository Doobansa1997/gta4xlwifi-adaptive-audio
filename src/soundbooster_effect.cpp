#include "soundbooster_effect_abi.h"
#include "soundbooster_engine.h"
#include "../third-party/picosha2.h"

#include <algorithm>
#include <android/log.h>
#include <cerrno>
#include <cmath>
#include <cstring>
#include <memory>
#include <mutex>
#include <type_traits>
#include <unistd.h>
#include <cstdio>

#ifndef SB_ENGINE_PATH
#error "A reviewed engine path and parameter payload must be supplied by the experimental builder"
#endif
#ifndef SB_ENGINE_HASH
#error "A reviewed architecture-specific engine hash must be supplied"
#endif

namespace {
using namespace sbfx;
constexpr Descriptor description{type, implementation, 0x20000, 128 | 512 | 4096 | 16384,
                                0, 0, "Experimental gta4xlwifi SoundBooster bridge", "Adaptive Audio"};
struct Context {
    const Interface* interface;
    std::mutex mutex;
    sb::Parameters parameters;
    std::unique_ptr<sb::Engine> engine;
    std::array<int16_t, 8192> pcm16_scratch;
    std::array<float, 8192> float_scratch;
    Config config{};
    bool configured = false, enabled = false;
    uint32_t device = 0;
    float volume = 1.0f;
    uint64_t processed_frames = 0, bypassed_frames = 0;
};
static_assert(std::is_standard_layout_v<Context> && offsetof(Context, interface) == 0);
int failure(const char* message, int error) {
    __android_log_print(ANDROID_LOG_ERROR, "AdaptiveSoundBooster", "%s (%d)", message, error);
    return error;
}
Context* context(Handle handle) { return reinterpret_cast<Context*>(handle); }
bool equal(const Uuid& a, const Uuid& b) { return std::memcmp(&a, &b, sizeof(a)) == 0; }
int accumulate(void* output, const void* input, size_t samples, bool floating) {
    if (floating) {
        auto* destination = static_cast<float*>(output);
        const auto* source = static_cast<const float*>(input);
        for (size_t i = 0; i < samples; ++i) {
            if (!std::isfinite(destination[i]) || !std::isfinite(source[i]))
                return failure("Nonfinite float accumulation buffer", -EINVAL);
            if (!std::isfinite(destination[i] + source[i]))
                return failure("Float accumulation overflow", -EOVERFLOW);
        }
        for (size_t i = 0; i < samples; ++i) destination[i] += source[i];
    } else {
        auto* destination = static_cast<int16_t*>(output);
        const auto* source = static_cast<const int16_t*>(input);
        for (size_t i = 0; i < samples; ++i)
            destination[i] = static_cast<int16_t>(
                std::clamp(int(destination[i]) + int(source[i]), -32768, 32767));
    }
    return 0;
}
void verify(const char* path, const char* expected) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error("Cannot open reviewed SoundBooster input");
    picosha2::hash256_one_by_one hasher;
    std::array<char, 8192> block{};
    while (file.read(block.data(), block.size()) || file.gcount()) {
        hasher.process(block.data(), block.data() + file.gcount());
    }
    if (!file.eof()) throw std::runtime_error("Failed reading SoundBooster input");
    hasher.finish();
    if (picosha2::get_hash_hex_string(hasher) != expected)
        throw std::runtime_error("SoundBooster input hash mismatch");
}
int32_t get_descriptor(Handle handle, Descriptor* output) {
    if (!handle || !output) return failure("Invalid descriptor request", -EINVAL);
    *output = description;
    return 0;
}
int32_t process(Handle handle, Buffer* input, Buffer* output) {
    if (!handle || !input || !output || !input->raw || !output->raw ||
        input->frames == 0 || input->frames > 4096 || output->frames != input->frames)
        return failure("Invalid PCM buffers", -EINVAL);
    auto& state = *context(handle);
    std::unique_lock<std::mutex> lock(state.mutex, std::try_to_lock);
    if (!lock.owns_lock()) return failure("Concurrent effect command", -EAGAIN);
    if (!state.configured) return failure("Effect has no accepted PCM configuration", -ENODATA);
    const bool floating = state.config.input.format == 5;
    const bool accumulating = state.config.output.access == 2;
    const size_t bytes = input->frames * (floating ? 8 : 4);
    if (!state.enabled || state.device != speaker) {
        if (accumulating) {
            const int result = accumulate(output->raw, input->raw, input->frames * 2, floating);
            if (result) return result;
        } else {
            std::memmove(output->raw, input->raw, bytes);
        }
        state.bypassed_frames += input->frames;
        return state.enabled ? 0 : -ENODATA;
    }
    if (floating) {
        const auto* samples = static_cast<const float*>(input->raw);
        if (!std::all_of(samples, samples + input->frames * 2,
                         [](float sample) { return std::isfinite(sample) && std::abs(sample) <= 1; }))
            return failure("Float input exceeds reviewed finite normalized range", -EINVAL);
        if (accumulating) {
            const auto* destination = static_cast<const float*>(output->raw);
            if (!std::all_of(destination, destination + input->frames * 2,
                             [](float sample) { return std::isfinite(sample); }))
                return failure("Nonfinite float accumulation destination", -EINVAL);
        }
    }
    void* processed = output->raw;
    if (accumulating)
        processed = floating ? static_cast<void*>(state.float_scratch.data()) :
                               static_cast<void*>(state.pcm16_scratch.data());
    if (state.engine->process(processed, input->raw, static_cast<int>(input->frames), state.volume) !=
        static_cast<int>(input->frames))
        return failure("Engine returned unexpected frame count", -EIO);
    const int result = accumulating ? accumulate(output->raw, processed, input->frames * 2, floating) : 0;
    if (!result) state.processed_frames += input->frames;
    return result;
}
bool valid(const BufferConfig& config, uint8_t access) {
    // HIDL 7 clears the obsolete direct-buffer bit and supplies buffers separately.
    return (config.mask == all_config || config.mask == pcm_config) &&
        config.rate == 48000 && config.channels == 3 &&
        (config.format == 1 || config.format == 5) && config.access == access && !config.buffer.raw &&
        !config.provider.get && !config.provider.release && !config.provider.cookie;
}
int32_t command(Handle handle, uint32_t code, uint32_t size, void* data,
                uint32_t* reply_size, void* reply) {
    if (!handle) return failure("Null effect handle", -EINVAL);
    auto& state = *context(handle);
    std::lock_guard<std::mutex> lock(state.mutex);
    auto status = [&](int32_t value) -> int32_t {
        std::memcpy(reply, &value, sizeof(value));
        *reply_size = sizeof(value);
        if (value) failure("Effect command rejected", value);
        return 0;
    };
    const bool status_reply = code == Init || code == SetConfig || code == Enable || code == Disable;
    if (status_reply && (!reply || !reply_size || *reply_size < sizeof(int32_t)))
        return failure("Missing command status reply", -EINVAL);
    switch (code) {
    case Dump: {
        if (!data || size != sizeof(int32_t)) return failure("Invalid dump descriptor", -EINVAL);
        int32_t fd;
        std::memcpy(&fd, data, sizeof(fd));
        if (fd < 0) return failure("Invalid dump descriptor", -EINVAL);
        const int result = dprintf(fd,
            "SoundBooster configured=%u enabled=%u device=0x%x volume=%.6f "
            "rate=%u format=%u input_mask=0x%x output_mask=0x%x "
            "processed_frames=%llu bypassed_frames=%llu\n",
            unsigned(state.configured), unsigned(state.enabled), state.device, state.volume,
            state.config.input.rate, unsigned(state.config.input.format),
            unsigned(state.config.input.mask), unsigned(state.config.output.mask),
            static_cast<unsigned long long>(state.processed_frames),
            static_cast<unsigned long long>(state.bypassed_frames));
        return result < 0 ? failure("Cannot write effect diagnostics", -EIO) : 0;
    }
    case Init:
        if (size) return status(-EINVAL);
        if (state.engine) state.engine->clear();
        state.enabled = false;
        state.device = 0;
        state.volume = 1;
        state.configured = false;
        return status(0);
    case SetConfig: {
        if (!data || size != sizeof(Config)) return status(-EINVAL);
        Config config;
        std::memcpy(&config, data, sizeof(config));
        if (state.enabled) return status(-ENOSYS);
        if (!valid(config.input, 1) || (!valid(config.output, 0) && !valid(config.output, 2)) ||
            config.input.format != config.output.format) return status(-EINVAL);
        try {
            verify(SB_ENGINE_PATH, SB_ENGINE_HASH);
            auto engine = std::make_unique<sb::Engine>();
            engine->initialize(SB_ENGINE_PATH, state.parameters, 2, config.input.format == 5 ? 3 : 0);
            state.engine = std::move(engine);
        } catch (const std::exception& error) {
            failure(error.what(), -EINVAL);
            return status(-EINVAL);
        }
        state.config = config;
        state.configured = true;
        state.engine->clear();
        return status(0);
    }
    case GetConfig:
        if (size || !state.configured || !reply || !reply_size || *reply_size < sizeof(Config))
            return failure("Invalid get-config request", -EINVAL);
        std::memcpy(reply, &state.config, sizeof(Config));
        *reply_size = sizeof(Config);
        return 0;
    case Enable:
    case Disable:
        if (size || !state.configured) return status(-EINVAL);
        state.engine->clear();
        state.enabled = code == Enable;
        return status(0);
    case Reset:
        if (size) return failure("Invalid reset request", -EINVAL);
        if (state.engine) state.engine->clear();
        return 0;
    case SetDevice: {
        if (!data || size != sizeof(uint32_t)) return failure("Invalid device payload", -EINVAL);
        uint32_t device;
        std::memcpy(&device, data, sizeof(device));
        if (state.device != device && state.engine) state.engine->clear();
        state.device = device;
        return 0;
    }
    case SetVolume: {
        if (!data || size != 2 * sizeof(uint32_t)) return failure("Invalid volume payload", -EINVAL);
        std::array<uint32_t, 2> volumes;
        std::memcpy(volumes.data(), data, size);
        if (volumes[0] > unity_volume || volumes[1] > unity_volume)
            return failure("Volume exceeds unity", -EINVAL);
        // VOLUME_IND only selects engine dynamics; Android retains responsibility for attenuation.
        state.volume = static_cast<float>(std::min(volumes[0], volumes[1])) / unity_volume;
        return 0;
    }
    default:
        return failure("Unsupported effect command", -ENOSYS);
    }
}
const Interface interface{process, command, get_descriptor, nullptr};
int32_t create(const Uuid* uuid, int32_t, int32_t, Handle* output) {
    if (!output) return failure("Null factory output", -EINVAL);
    *output = nullptr;
    if (!uuid || !equal(*uuid, implementation)) return failure("Unknown effect UUID", -ENOENT);
    try {
        verify(SB_ENGINE_PATH, SB_ENGINE_HASH);
        verify(SB_PARAMETER_PATH, SB_PARAMETER_HASH);
        auto state = std::make_unique<Context>();
        state->interface = &interface;
        state->parameters = sb::read_parameters(SB_PARAMETER_PATH);
        *output = reinterpret_cast<Handle>(state.release());
        return 0;
    } catch (const std::exception& error) {
        return failure(error.what(), -EINVAL);
    }
}
int32_t release(Handle handle) {
    if (!handle) return failure("Null release handle", -EINVAL);
    delete context(handle);
    return 0;
}
int32_t library_descriptor(const Uuid* uuid, Descriptor* output) {
    if (!uuid || !output || !equal(*uuid, implementation)) return failure("Unknown descriptor UUID", -EINVAL);
    *output = description;
    return 0;
}
}
extern "C" {
__attribute__((visibility("default")))
sbfx::Library AELI{0x41454c54, 0x30000, "Experimental SoundBooster bridge", "Adaptive Audio",
                  create, release, library_descriptor};
}
