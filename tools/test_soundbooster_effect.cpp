#include "../src/soundbooster_effect_abi.h"
#include "../src/soundbooster_engine.h"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <link.h>
#include <stdexcept>
#include <type_traits>
#include <unistd.h>
#include <vector>

#ifdef SB_AOSP_ABI
#include <hardware/audio_effect.h>
static_assert(sizeof(sbfx::Descriptor) == sizeof(effect_descriptor_t));
static_assert(sizeof(sbfx::Buffer) == sizeof(audio_buffer_t));
static_assert(sizeof(sbfx::Config) == sizeof(effect_config_t));
static_assert(sizeof(sbfx::Interface) == sizeof(effect_interface_s));
static_assert(offsetof(sbfx::Descriptor, api) == offsetof(effect_descriptor_t, apiVersion));
static_assert(offsetof(sbfx::Descriptor, name) == offsetof(effect_descriptor_t, name));
static_assert(offsetof(sbfx::BufferConfig, provider) == offsetof(buffer_config_t, bufferProvider));
static_assert(offsetof(sbfx::BufferConfig, format) == offsetof(buffer_config_t, format));
static_assert(offsetof(sbfx::BufferConfig, mask) == offsetof(buffer_config_t, mask));
static_assert(offsetof(sbfx::Library, create) == offsetof(audio_effect_library_t, create_effect));
static_assert(offsetof(sbfx::Library, release) == offsetof(audio_effect_library_t, release_effect));
static_assert(offsetof(sbfx::Library, descriptor) == offsetof(audio_effect_library_t, get_descriptor));
static_assert(uint32_t(sbfx::Init) == EFFECT_CMD_INIT && uint32_t(sbfx::SetConfig) == EFFECT_CMD_SET_CONFIG);
static_assert(uint32_t(sbfx::SetDevice) == EFFECT_CMD_SET_DEVICE &&
              uint32_t(sbfx::SetVolume) == EFFECT_CMD_SET_VOLUME);
static_assert(uint32_t(sbfx::GetConfig) == EFFECT_CMD_GET_CONFIG && sbfx::all_config == EFFECT_CONFIG_ALL);
static_assert(uint32_t(sbfx::Dump) == EFFECT_CMD_DUMP &&
              sbfx::pcm_config == (EFFECT_CONFIG_ALL & ~EFFECT_CONFIG_BUFFER));
static_assert(sbfx::speaker == AUDIO_DEVICE_OUT_SPEAKER && AUDIO_FORMAT_PCM_16_BIT == 1);
static_assert(AUDIO_CHANNEL_OUT_STEREO == 3 && EFFECT_BUFFER_ACCESS_READ == 1);
static_assert(AUDIO_FORMAT_PCM_FLOAT == 5);
static_assert(EFFECT_BUFFER_ACCESS_ACCUMULATE == 2 && EFFECT_BUFFER_ACCESS_WRITE == 0);
static_assert(EFFECT_FLAG_DEVICE_IND == 512 && EFFECT_FLAG_VOLUME_IND == 128);
#endif

namespace {
size_t checks = 0;
struct Timing {
    std::vector<double> loads;
    template <typename Function> int measure(size_t frames, Function call) {
        const auto start = std::chrono::steady_clock::now();
        int result = call();
        const auto stop = std::chrono::steady_clock::now();
        loads.push_back(std::chrono::duration<double>(stop - start).count() / (frames / 48000.0));
        return result;
    }
    double percentile(double quantile) {
        std::sort(loads.begin(), loads.end());
        return loads[static_cast<size_t>(std::ceil(quantile * loads.size())) - 1];
    }
};
void require(bool condition, const char* message) {
    ++checks;
    if (!condition) throw std::runtime_error(message);
}
struct RuntimeMappings { bool platform = false, vendor = false; };
RuntimeMappings runtime_mappings() {
    RuntimeMappings result;
    std::ifstream maps("/proc/self/maps");
    require(bool(maps), "Cannot inspect process maps for runtime isolation");
    std::string line;
    while (std::getline(maps, line)) {
#ifdef SB_STATIC_RUNTIME
        require(line.find("/libc++_shared.so") == std::string::npos,
                "NDK shared C++ runtime loaded in static-runtime test");
#endif
        result.platform |= line.find(sizeof(void*) == 4 ? "/system/lib/libc++.so" :
                                                         "/system/lib64/libc++.so") != std::string::npos;
        result.vendor |= line.find(sizeof(void*) == 4 ? "/vendor/lib/libc++.so" :
                                                       "/vendor/lib64/libc++.so") != std::string::npos;
    }
    require(maps.eof(), "Cannot finish reading process runtime mappings");
    return result;
}
struct EngineMapping {
    const char* path;
    uintptr_t base = 0;
    const ElfW(Phdr)* headers = nullptr;
    size_t count = 0, matches = 0;
};
int find_engine(dl_phdr_info* info, size_t, void* data) {
    auto& mapping = *static_cast<EngineMapping*>(data);
    if (std::strcmp(info->dlpi_name, mapping.path) == 0) {
        mapping.base = info->dlpi_addr;
        mapping.headers = info->dlpi_phdr;
        mapping.count = info->dlpi_phnum;
        ++mapping.matches;
    }
    return 0;
}
std::string engine_bindings(const char* engine_path, const char* effect_path) {
    struct Relocation { uintptr_t offset; const char* symbol; };
    const Relocation relocations[] = SB_ENGINE_RELOCATIONS;
    EngineMapping mapping{engine_path};
    dl_iterate_phdr(find_engine, &mapping);
    require(mapping.matches == 1 && mapping.headers, "Cannot uniquely locate loaded engine");
    struct Binding { std::string symbol, provider; size_t slots = 0; };
    std::vector<Binding> bindings;
    const std::string shared_path = std::string(engine_path).substr(
        0, std::string(engine_path).find_last_of('/') + 1) + "libc++_shared.so";
    for (const auto& relocation : relocations) {
        const uintptr_t address = mapping.base + relocation.offset;
        bool readable = false;
        for (size_t i = 0; i < mapping.count; ++i) {
            const auto& header = mapping.headers[i];
            if (header.p_type == PT_LOAD && (header.p_flags & PF_R) &&
                relocation.offset >= header.p_vaddr && header.p_memsz >= sizeof(uintptr_t) &&
                relocation.offset - header.p_vaddr <= header.p_memsz - sizeof(uintptr_t))
                readable = true;
        }
        require(readable && address >= mapping.base, "Engine relocation is not within a readable segment");
        uintptr_t target;
        std::memcpy(&target, reinterpret_cast<const void*>(address), sizeof(target));
        Dl_info info{};
        require(target && dladdr(reinterpret_cast<const void*>(target), &info) && info.dli_fname,
                "Unresolved engine C++ relocation");
        const std::string path = info.dli_fname;
        std::string provider;
        if (path == effect_path) provider = "bridge_embedded";
        else if (path == shared_path) provider = "ndk_shared";
        else if (path == (sizeof(void*) == 4 ? "/system/lib/libc++.so" : "/system/lib64/libc++.so"))
            provider = "platform_cpp";
        else if (path == (sizeof(void*) == 4 ? "/vendor/lib/libc++.so" : "/vendor/lib64/libc++.so"))
            provider = "vendor_cpp";
        else throw std::runtime_error("Unexpected engine C++ provider: " + path);
        auto found = std::find_if(bindings.begin(), bindings.end(), [&](const Binding& binding) {
            return binding.symbol == relocation.symbol;
        });
        if (found == bindings.end()) bindings.push_back({relocation.symbol, provider, 1});
        else {
            require(found->provider == provider, "Inconsistent provider for one engine C++ symbol");
            ++found->slots;
        }
    }
    std::string result = "[";
    for (const auto& binding : bindings) {
        if (result.size() > 1) result += ",";
        result += "{\"symbol\":\"" + binding.symbol + "\",\"provider\":\"" + binding.provider +
                  "\",\"slots\":" + std::to_string(binding.slots) + "}";
    }
    return result + "]";
}
struct Effect {
    sbfx::Library* library;
    sbfx::Handle handle = nullptr;
    ~Effect() { if (handle) library->release(handle); }
    int status(uint32_t command, uint32_t size = 0, void* data = nullptr) {
        int32_t status = 1234;
        uint32_t reply_size = sizeof(status);
        require((*handle)->command(handle, command, size, data, &reply_size, &status) == 0,
                "Command transport failed");
        require(reply_size == sizeof(status), "Wrong command status size");
        return status;
    }
    int command(uint32_t command, uint32_t size = 0, void* data = nullptr) {
        return (*handle)->command(handle, command, size, data, nullptr, nullptr);
    }
    void route(uint32_t device) {
        require(command(sbfx::SetDevice, sizeof(device), &device) == 0, "Routing command failed");
    }
};
sbfx::Config configuration() {
    sbfx::Config config{};
    for (auto* side : {&config.input, &config.output}) {
        side->rate = 48000;
        side->channels = 3;
        side->format = 1;
        side->mask = sbfx::all_config;
    }
    config.input.access = 1;
    return config;
}
template <typename Sample>
size_t accumulation_matrix(Effect& effect, const char* engine_path, sb::Parameters& parameters) {
    constexpr bool floating = std::is_same_v<Sample, float>;
    auto config = configuration();
    config.input.mask = config.output.mask = sbfx::pcm_config;
    config.input.format = config.output.format = floating ? 5 : 1;
    config.output.access = 2;
    require(effect.status(sbfx::SetConfig, sizeof(config), &config) == 0, "Accumulation config failed");
    require(effect.status(sbfx::Enable) == 0, "Accumulation enable failed");
    effect.route(sbfx::speaker);
    sb::Engine reference;
    reference.initialize(engine_path, parameters, 2, floating ? 3 : 0);
    size_t compared_frames = 0;
    for (bool inplace : {false, true}) {
        for (uint32_t volume : {sbfx::unity_volume, sbfx::unity_volume / 4, 0u}) {
            uint32_t volumes[] = {volume, volume};
            require(effect.command(sbfx::SetVolume, sizeof(volumes), volumes) == 0, "Accumulation volume failed");
            require(effect.command(sbfx::Reset) == 0, "Accumulation reset failed");
            reference.clear();
            for (size_t frames : {1u, 48u, 96u, 256u, 1024u, 4096u}) {
                std::vector<Sample> input(frames * 2), processed(frames * 2), expected(frames * 2);
                std::vector<Sample> guarded(frames * 2 + 32, Sample(12345));
                for (int block = 0; block < 16; ++block) {
                    for (size_t i = 0; i < frames * 2; ++i) {
                        input[i] = Sample((floating ? 0.1 : 3000) *
                            std::sin(2 * std::acos(-1.0) * 157 * (block * frames + i / 2) / 48000));
                        guarded[16 + i] = inplace ? input[i] : Sample((i & 1 ? -1 : 1) *
                                                                 (floating ? 1.25 : 30000));
                    }
                    require(reference.process(processed.data(), input.data(), static_cast<int>(frames),
                            static_cast<float>(volume) / sbfx::unity_volume) == static_cast<int>(frames),
                            "Accumulation reference failed");
                    for (size_t i = 0; i < frames * 2; ++i) {
                        if constexpr (floating) {
                            expected[i] = guarded[16 + i] + processed[i];
                        } else {
                            const int sum = int(guarded[16 + i]) + int(processed[i]);
                            expected[i] = Sample(sum > 32767 ? 32767 : sum < -32768 ? -32768 : sum);
                        }
                    }
                    const auto original_input = input;
                    sbfx::Buffer in{frames, inplace ? guarded.data() + 16 : input.data()};
                    sbfx::Buffer out{frames, guarded.data() + 16};
                    require((*effect.handle)->process(effect.handle, &in, &out) == 0,
                            "Accumulation process failed");
                    require(std::memcmp(expected.data(), guarded.data() + 16,
                                        expected.size() * sizeof(Sample)) == 0,
                            "Accumulation differs from original engine plus destination");
                    require(std::all_of(guarded.begin(), guarded.begin() + 16,
                                        [](Sample sample) { return sample == Sample(12345); }) &&
                            std::all_of(guarded.end() - 16, guarded.end(),
                                        [](Sample sample) { return sample == Sample(12345); }),
                            "Accumulation overwrote canary");
                    if (!inplace) require(input == original_input, "Accumulation modified READ input");
                    compared_frames += frames;
                }
            }
        }
    }
    const Sample high = floating ? Sample(0.75) : Sample(30000);
    const Sample low = -high;
    std::array<Sample, 2> input{high, low}, output{};
    sbfx::Buffer in{1, input.data()}, out{1, output.data()};
    for (uint32_t device : {0u, 4u, 8u, 128u, 0x4000000u, 6u}) {
        effect.route(device);
        output = input;
        require((*effect.handle)->process(effect.handle, &in, &out) == 0,
                "Accumulation bypass failed");
        require(output[0] == (floating ? Sample(1.5) : Sample(32767)) &&
                output[1] == (floating ? Sample(-1.5) : Sample(-32768)),
                "Bypass accumulation lost existing signal or clipped float headroom");
    }
    if constexpr (floating) {
        effect.route(sbfx::speaker);
        for (bool invalid_input : {false, true}) {
            input = {high, low}; output = {high, low};
            (invalid_input ? input : output)[1] = std::numeric_limits<float>::quiet_NaN();
            const auto before = output;
            require((*effect.handle)->process(effect.handle, &in, &out) == -EINVAL &&
                    !std::memcmp(before.data(), output.data(), 2 * sizeof(Sample)),
                    "Invalid float accumulation changed destination");
        }
        effect.route(4);
        input.fill(std::numeric_limits<float>::max());
        output = input;
        const auto before = output;
        require((*effect.handle)->process(effect.handle, &in, &out) == -EOVERFLOW &&
                output == before, "Float accumulation overflow was not rejected atomically");
    }
    effect.route(sbfx::speaker);
    require(effect.status(sbfx::Disable) == 0, "Accumulation disable failed");
    input = {high, low}; output = input;
    require((*effect.handle)->process(effect.handle, &in, &out) == -ENODATA &&
            output[0] == (floating ? Sample(1.5) : Sample(32767)) &&
            output[1] == (floating ? Sample(-1.5) : Sample(-32768)),
            "Disabled accumulation did not preserve existing signal");
    return compared_frames;
}
}

int main(int argc, char** argv) {
    try {
        alarm(30);
        if (argc != 4) throw std::runtime_error("Usage: effect-test EFFECT ENGINE PARAMETERS");
        const auto runtime_before = runtime_mappings();
        void* library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
        if (!library) throw std::runtime_error(dlerror());
        auto* api = sb::symbol<sbfx::Library*>(library, "AELI");
        require(api->tag == 0x41454c54 && api->version == 0x30000, "Invalid effect library ABI");
        sbfx::Descriptor descriptor{};
        require(api->descriptor(&sbfx::implementation, &descriptor) == 0, "Descriptor failed");
        require(descriptor.api == 0x20000 && (descriptor.flags & (128 | 512)) == (128 | 512),
                "Missing volume/device indications");
        require(!(descriptor.flags & 64), "Effect must not claim volume ownership");
        sbfx::Uuid wrong{};
        sbfx::Handle unknown = nullptr;
        require(api->create(&wrong, 0, 0, &unknown) == -ENOENT && !unknown, "Unknown UUID accepted");
        require(api->create(&sbfx::implementation, 0, 0, nullptr) == -EINVAL,
                "Null factory output accepted");
        require(api->descriptor(&wrong, &descriptor) == -EINVAL, "Unknown descriptor UUID accepted");
        {
            std::fstream payload(argv[3], std::ios::in | std::ios::out | std::ios::binary);
            char original;
            require(bool(payload.read(&original, 1)), "Cannot read hash-refusal fixture");
            const char changed = original ^ 1;
            payload.seekp(0);
            require(bool(payload.write(&changed, 1).flush()), "Cannot write hash-refusal fixture");
            sbfx::Handle invalid = nullptr;
            const int result = api->create(&sbfx::implementation, 0, 0, &invalid);
            payload.seekp(0);
            require(bool(payload.write(&original, 1).flush()), "Cannot restore hash-refusal fixture");
            if (invalid) api->release(invalid);
            require(result == -EINVAL && !invalid, "Modified parameter payload was accepted");
        }
        {
            Effect effect{api};
            require(api->create(&sbfx::implementation, 0, 0, &effect.handle) == 0 && effect.handle,
                    "Effect creation failed");
            require(effect.status(sbfx::Init) == 0, "Init failed");
            require(effect.status(sbfx::Enable) == -EINVAL, "Enabled before PCM configuration");
            auto config = configuration();
            auto bad = config;
            bad.input.rate = bad.output.rate = 44100;
            require(effect.status(sbfx::SetConfig, sizeof(bad), &bad) == -EINVAL, "Accepted 44.1kHz");
            bad = config; bad.output.format = 5;
            require(effect.status(sbfx::SetConfig, sizeof(bad), &bad) == -EINVAL, "Accepted mixed formats");
            bad = config; bad.output.access = 1;
            require(effect.status(sbfx::SetConfig, sizeof(bad), &bad) == -EINVAL, "Accepted READ output");
            bad = config; bad.input.channels = bad.output.channels = 1;
            require(effect.status(sbfx::SetConfig, sizeof(bad), &bad) == -EINVAL, "Accepted mono");
            for (const uint16_t mask : {uint16_t(0), uint16_t(14), uint16_t(22), uint16_t(26),
                                        uint16_t(28), uint16_t(62), uint16_t(65535)}) {
                bad = config;
                bad.input.mask = bad.output.mask = mask;
                require(effect.status(sbfx::SetConfig, sizeof(bad), &bad) == -EINVAL,
                        "Accepted missing or unknown HIDL PCM fields");
            }
            require(effect.status(sbfx::SetConfig, sizeof(config), &config) == 0, "Config failed");
            config.input.mask = config.output.mask = sbfx::pcm_config;
            require(effect.status(sbfx::SetConfig, sizeof(config), &config) == 0,
                    "HIDL 7 config without obsolete buffer bit rejected");
            sbfx::Config readback{};
            uint32_t reply_size = sizeof(readback);
            require((*effect.handle)->command(effect.handle, sbfx::GetConfig, 0, nullptr,
                    &reply_size, &readback) == 0 && reply_size == sizeof(readback) &&
                    !std::memcmp(&readback, &config, sizeof(config)), "Config readback mismatch");
            require(effect.status(sbfx::Enable) == 0, "Enable failed");
            require(effect.status(sbfx::SetConfig, sizeof(config), &config) == -ENOSYS,
                    "Reconfigured active effect");
            require(effect.command(0xdead) == -ENOSYS, "Unknown command accepted");
            require(effect.command(sbfx::SetDevice, 0, nullptr) == -EINVAL, "Malformed route accepted");
            require((*effect.handle)->command(effect.handle, sbfx::Enable, 0, nullptr,
                                               nullptr, nullptr) == -EINVAL,
                    "Missing status reply accepted");
            uint32_t volumes[] = {sbfx::unity_volume, sbfx::unity_volume};
            require(effect.command(sbfx::SetVolume, sizeof(volumes), volumes) == 0, "Volume failed");
            volumes[0] += 1;
            require(effect.command(sbfx::SetVolume, sizeof(volumes), volumes) == -EINVAL,
                    "Volume above unity accepted");
            volumes[0] = sbfx::unity_volume;

            std::vector<int16_t> input(512), output(512);
            for (size_t i = 0; i < input.size(); ++i) input[i] = static_cast<int16_t>(i - 256);
            sbfx::Buffer in{256, input.data()}, out{256, output.data()};
            sbfx::Buffer empty{0, input.data()};
            require((*effect.handle)->process(effect.handle, &empty, &out) == -EINVAL,
                    "Empty process buffer accepted");
            sbfx::Buffer oversized{4097, input.data()};
            require((*effect.handle)->process(effect.handle, &oversized, &oversized) == -EINVAL,
                    "Oversized process buffer accepted");
            require((*effect.handle)->process(effect.handle, nullptr, &out) == -EINVAL,
                    "Null process buffer accepted");
            for (uint32_t device : {0u, 4u, 8u, 128u, 0x4000000u, 6u}) {
                effect.route(device);
                std::fill(output.begin(), output.end(), 0);
                require((*effect.handle)->process(effect.handle, &in, &out) == 0 &&
                        output == input, "Non-speaker route modified PCM");
                sbfx::Buffer inplace{256, input.data()};
                require((*effect.handle)->process(effect.handle, &inplace, &inplace) == 0,
                        "In-place bypass failed");
            }
            require(effect.command(sbfx::Dump) == -EINVAL, "Missing dump descriptor accepted");
            int32_t invalid_fd = -1;
            require(effect.command(sbfx::Dump, sizeof(invalid_fd), &invalid_fd) == -EINVAL,
                    "Negative dump descriptor accepted");
            int dump_pipe[2];
            require(pipe(dump_pipe) == 0, "Cannot create diagnostics pipe");
            int32_t dump_fd = dump_pipe[1];
            const int dump_result = effect.command(sbfx::Dump, sizeof(dump_fd), &dump_fd);
            close(dump_pipe[1]);
            char dump[512]{};
            const auto dump_size = read(dump_pipe[0], dump, sizeof(dump) - 1);
            close(dump_pipe[0]);
            require(dump_result == 0 && dump_size > 0 &&
                    std::strstr(dump, "configured=1 enabled=1") &&
                    std::strstr(dump, "input_mask=0x1e output_mask=0x1e") &&
                    std::strstr(dump, "processed_frames=0 bypassed_frames=3072"),
                    "HIDL diagnostics or bypass frame accounting mismatch");
            effect.route(sbfx::speaker);
            require(effect.command(sbfx::Reset) == 0, "Reset failed");
            auto parameters = sb::read_parameters(argv[3]);
            sb::Engine reference;
            reference.initialize(argv[2], parameters, 2);
            reference.clear();
            bool changed = false;
            size_t compared_frames = 0;
            Timing pcm16_timing, float_timing;
            for (uint32_t volume : {sbfx::unity_volume, sbfx::unity_volume / 4, 0u}) {
                volumes[0] = volumes[1] = volume;
                require(effect.command(sbfx::SetVolume, sizeof(volumes), volumes) == 0,
                        "Valid volume rejected");
                require(effect.command(sbfx::Reset) == 0, "Reset failed");
                reference.clear();
                for (size_t frames : {48u, 96u, 256u, 1024u}) {
                    input.resize(frames * 2);
                    std::vector<int16_t> guarded(frames * 2 + 32, 12345);
                    std::vector<int16_t> expected(frames * 2);
                    for (int block = 0; block < 16; ++block) {
                        for (size_t index = 0; index < frames; ++index) {
                            int16_t sample = static_cast<int16_t>(
                                3000 * std::sin(2 * std::acos(-1.0) * 157 *
                                               (block * frames + index) / 48000));
                            input[index * 2] = input[index * 2 + 1] = sample;
                        }
                        in = {frames, input.data()};
                        out = {frames, guarded.data() + 16};
                        require(reference.process(expected.data(), input.data(),
                                static_cast<int>(frames), static_cast<float>(volume) / sbfx::unity_volume) ==
                                static_cast<int>(frames), "Reference process failed");
                        require(pcm16_timing.measure(frames, [&] {
                                    return (*effect.handle)->process(effect.handle, &in, &out);
                                }) == 0,
                                "Speaker process failed");
                        require(std::equal(expected.begin(), expected.end(), guarded.begin() + 16),
                                "Adapter output differs from direct engine");
                        require(std::all_of(guarded.begin(), guarded.begin() + 16,
                                            [](int16_t value) { return value == 12345; }) &&
                                std::all_of(guarded.end() - 16, guarded.end(),
                                            [](int16_t value) { return value == 12345; }),
                                "Output buffer overflow");
                        changed |= expected != input;
                        compared_frames += frames;
                    }
                }
            }
            require(changed, "Speaker processing was bypassed");
            require(effect.command(sbfx::Reset) == 0, "In-place reset failed");
            reference.clear();
            input.assign(512, 1234);
            std::vector<int16_t> expected(512);
            require(reference.process(expected.data(), input.data(), 256, 0) == 256,
                    "In-place reference failed");
            in = {256, input.data()};
            require((*effect.handle)->process(effect.handle, &in, &in) == 0 &&
                    expected == input, "In-place processing mismatch");
            compared_frames += 256;
            output.resize(512);
            out = {256, output.data()};
            out.frames = in.frames - 1;
            require((*effect.handle)->process(effect.handle, &in, &out) == -EINVAL,
                    "Mismatched output length accepted");
            out.frames = in.frames;
            require(effect.status(sbfx::Disable) == 0, "Disable failed");
            require((*effect.handle)->process(effect.handle, &in, &out) == -ENODATA &&
                    std::equal(input.begin(), input.end(), static_cast<int16_t*>(out.raw)),
                    "Disabled effect did not bypass");
            config.input.format = config.output.format = 5;
            require(effect.status(sbfx::SetConfig, sizeof(config), &config) == 0, "Float config failed");
            require(effect.status(sbfx::Enable) == 0, "Float enable failed");
            std::vector<float> float_input(512, 0.1f), float_output(512, 0.0f);
            float_input[0] = std::numeric_limits<float>::quiet_NaN();
            float_input[1] = std::numeric_limits<float>::infinity();
            float_input[2] = -0.0f;
            for (uint32_t device : {0u, 4u, 8u, 128u, 0x4000000u, 6u}) {
                effect.route(device);
                in = {256, float_input.data()}; out = {256, float_output.data()};
                require((*effect.handle)->process(effect.handle, &in, &out) == 0 &&
                        std::memcmp(float_input.data(), float_output.data(),
                                    float_input.size() * sizeof(float)) == 0, "Float non-speaker bypass failed");
            }
            std::fill(float_input.begin(), float_input.end(), 0.1f);
            effect.route(sbfx::speaker);
            for (float invalid : {std::numeric_limits<float>::quiet_NaN(),
                                  std::numeric_limits<float>::infinity(), 1.01f, -1.01f}) {
                float_input[0] = invalid;
                std::fill(float_output.begin(), float_output.end(), 0.25f);
                require((*effect.handle)->process(effect.handle, &in, &out) == -EINVAL &&
                        std::all_of(float_output.begin(), float_output.end(),
                                    [](float value) { return value == 0.25f; }),
                        "Invalid float input accepted or output modified");
            }
            sb::Engine float_reference;
            float_reference.initialize(argv[2], parameters, 2, 3);
            bool float_changed = false;
            for (uint32_t volume : {sbfx::unity_volume, sbfx::unity_volume / 4, 0u}) {
                volumes[0] = volumes[1] = volume;
                require(effect.command(sbfx::SetVolume, sizeof(volumes), volumes) == 0, "Float volume failed");
                require(effect.command(sbfx::Reset) == 0, "Float reset failed");
                float_reference.clear();
                for (size_t frames : {48u, 96u, 256u, 1024u}) {
                    float_input.resize(frames * 2);
                    std::vector<float> guarded(frames * 2 + 32, 12345);
                    std::vector<float> expected_float(frames * 2);
                    for (int block = 0; block < 16; ++block) {
                        for (size_t index = 0; index < frames; ++index) {
                            float sample = 0.1f * std::sin(2 * std::acos(-1.0) * 157 *
                                                         (block * frames + index) / 48000);
                            float_input[2 * index] = float_input[2 * index + 1] = sample;
                        }
                        in = {frames, float_input.data()}; out = {frames, guarded.data() + 16};
                        require(float_reference.process(expected_float.data(), float_input.data(),
                                static_cast<int>(frames), static_cast<float>(volume) / sbfx::unity_volume) ==
                                static_cast<int>(frames), "Float reference failed");
                        require(float_timing.measure(frames, [&] {
                                    return (*effect.handle)->process(effect.handle, &in, &out);
                                }) == 0,
                                "Float speaker process failed");
                        require(std::memcmp(expected_float.data(), guarded.data() + 16,
                                            expected_float.size() * sizeof(float)) == 0,
                                "Float adapter differs from direct engine");
                        require(std::all_of(expected_float.begin(), expected_float.end(),
                                            [](float value) { return std::isfinite(value); }),
                                "Nonfinite float output");
                        require(std::all_of(guarded.begin(), guarded.begin() + 16,
                                            [](float value) { return value == 12345; }) &&
                                std::all_of(guarded.end() - 16, guarded.end(),
                                            [](float value) { return value == 12345; }),
                                "Float output overflow");
                        float_changed |= expected_float != float_input;
                        compared_frames += frames;
                    }
                }
            }
            require(float_changed, "Float engine did not modify signal");
            require(effect.command(sbfx::Reset) == 0, "Float in-place reset failed");
            float_reference.clear();
            float_input.assign(512, 0.1f);
            std::vector<float> expected_float(512);
            require(float_reference.process(expected_float.data(), float_input.data(), 256, 0) == 256,
                    "Float in-place reference failed");
            in = {256, float_input.data()};
            require((*effect.handle)->process(effect.handle, &in, &in) == 0 &&
                    std::memcmp(expected_float.data(), float_input.data(),
                                expected_float.size() * sizeof(float)) == 0, "Float in-place mismatch");
            compared_frames += 256;
            float_output.resize(512);
            out = {256, float_output.data()};
            require(effect.status(sbfx::Disable) == 0, "Float disable failed");
            require((*effect.handle)->process(effect.handle, &in, &out) == -ENODATA &&
                    float_input == float_output, "Float disabled bypass failed");
            config = configuration();
            require(effect.status(sbfx::SetConfig, sizeof(config), &config) == 0,
                    "Reconfiguration back to PCM16 failed");
            require(effect.status(sbfx::Enable) == 0, "Reconfigured PCM16 enable failed");
            reference.clear();
            input.assign(512, 1234);
            expected.resize(512);
            require(reference.process(expected.data(), input.data(), 256, 0) == 256,
                    "Reconfigured PCM16 reference failed");
            in = {256, input.data()}; out = {256, expected.data()};
            std::vector<int16_t> actual(512);
            out.raw = actual.data();
            require((*effect.handle)->process(effect.handle, &in, &out) == 0 &&
                    expected == actual, "Reconfigured PCM16 processing mismatch");
            compared_frames += 256;
            require(effect.status(sbfx::Disable) == 0, "Final WRITE disable failed");
            size_t accumulation_frames = accumulation_matrix<int16_t>(effect, argv[2], parameters);
            accumulation_frames += accumulation_matrix<float>(effect, argv[2], parameters);
            const auto runtime_after = runtime_mappings();
            const auto bindings = engine_bindings(argv[2], argv[1]);
            std::printf("{\"format\":1,\"pointer_bits\":%zu,\"checks\":%zu,\"compared_frames\":%zu,"
                        "\"direct_engine_exact_match\":true,\"speaker_only_bypass_verified\":true,"
                        "\"pcm16_and_float_verified\":true,"
                        "\"hidl_pcm_mask_verified\":true,\"effect_dump_verified\":true,"
                        "\"accumulation_verified\":true,\"accumulation_compared_frames\":%zu,"
                        "\"android_service_integration_verified\":false,"
                        "\"process_timing\":["
                        "{\"pcm_format\":1,\"calls\":%zu,\"median_period_ratio\":%.9f,"
                        "\"p99_period_ratio\":%.9f,\"max_period_ratio\":%.9f},"
                        "{\"pcm_format\":5,\"calls\":%zu,\"median_period_ratio\":%.9f,"
                        "\"p99_period_ratio\":%.9f,\"max_period_ratio\":%.9f}],"
                        "\"ndk_shared_runtime_absent\":%s,"
                        "\"platform_shared_runtime_present\":%s,"
                        "\"vendor_shared_runtime_present\":%s,"
                        "\"engine_cpp_bindings\":%s,"
                        "\"aosp_header_abi_verified\":%s}\n", sizeof(void*) * 8, checks, compared_frames,
                        accumulation_frames, pcm16_timing.loads.size(), pcm16_timing.percentile(0.5),
                        pcm16_timing.percentile(0.99), pcm16_timing.percentile(1),
                        float_timing.loads.size(), float_timing.percentile(0.5),
                        float_timing.percentile(0.99), float_timing.percentile(1),
#ifdef SB_STATIC_RUNTIME
                        "true",
#else
                        "false",
#endif
                        runtime_before.platform || runtime_after.platform ? "true" : "false",
                        runtime_before.vendor || runtime_after.vendor ? "true" : "false",
                        bindings.c_str(),
#ifdef SB_AOSP_ABI
                        "true"
#else
                        "false"
#endif
                        );
        }
        require(dlclose(library) == 0, "Effect unload failed");
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "SoundBooster effect test failed: %s\n", error.what());
        return 1;
    }
}
