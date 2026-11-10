// Standalone in-memory probe: no Android audio APIs or playback.
#include "../src/soundbooster_engine.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <dlfcn.h>
#include <fstream>
#include <stdexcept>
#include <string>
#include <unistd.h>

int main(int argc, char** argv) {
    try {
        if (argc != 4) throw std::runtime_error("Usage: probe ENGINE PARAMETERS MODE");
        const std::string mode_arg(argv[3]);
        if (mode_arg != "1" && mode_arg != "2") throw std::runtime_error("Expected mode 1 or 2");
        const int mode = mode_arg == "1" ? 1 : 2;
        alarm(30);
        auto parameters = sb::read_parameters(argv[2]);
        std::printf("{\"engine_mode\":%d,\"sample_rate_hz\":48000,\"pcm_bits\":16,"
                    "\"frame_count_per_call\":256,\"cases\":[", mode);
        bool first = true;
        for (double frequency : {0.0, 157.0, 340.0, 1000.0, 7400.0}) {
            for (double level_db : {-36.0, -18.0, -6.0}) {
                sb::Engine engine;
                engine.initialize(argv[1], parameters, mode);
                constexpr size_t frames = 256;
                constexpr size_t samples = frames * 2;
                constexpr int blocks = 192;
                constexpr int guard = 0x13572468;
                std::array<int16_t, samples> source{};
                std::array<int32_t, samples + 64> destination{};
                double input_energy = 0, output_energy = 0;
                int peak = 0;
                size_t changed = 0, clipped = 0, measured = 0;
                for (int block = 0; block < blocks; ++block) {
                    for (size_t frame = 0; frame < frames; ++frame) {
                        const double phase = 2 * std::acos(-1.0) * frequency *
                                             (block * frames + frame) / 48000;
                        const auto value = static_cast<int16_t>(
                            std::lround(32767 * std::pow(10.0, level_db / 20) * std::sin(phase)));
                        source[2 * frame] = source[2 * frame + 1] = value;
                    }
                    destination.fill(guard);
                    void* output = destination.data() + 16;
                    if (engine.process(output, source.data(), frames, 1.0f) !=
                        static_cast<int>(frames))
                        throw std::runtime_error("Engine process returned an unexpected frame count");
                    if (!std::all_of(destination.begin(), destination.begin() + 16,
                                     [](int32_t value) { return value == guard; }) ||
                        !std::all_of(destination.begin() + 16 + samples / 2, destination.end(),
                                     [](int32_t value) { return value == guard; }))
                        throw std::runtime_error("Engine wrote beyond expected PCM16 stereo output");
                    const auto* result = static_cast<const int16_t*>(output);
                    if (block < blocks / 2) continue;
                    for (size_t index = 0; index < samples; ++index) {
                        const int value = result[index];
                        input_energy += static_cast<double>(source[index]) * source[index];
                        output_energy += static_cast<double>(value) * value;
                        peak = std::max(peak, std::abs(value));
                        changed += value != source[index];
                        clipped += value == -32768 || value == 32767;
                        ++measured;
                    }
                }
                if (frequency == 0 && output_energy != 0)
                    throw std::runtime_error("Nonzero output for fresh-state silence");
                if (frequency != 0 && output_energy == 0)
                    throw std::runtime_error("Engine produced no output for tone");
                std::printf("%s{\"frequency_hz\":%.0f,\"input_dbfs\":%.0f,"
                            "\"input_energy\":%.0f,\"output_energy\":%.0f,\"peak\":%d,"
                            "\"changed_samples\":%zu,\"clipped_samples\":%zu,\"measured_samples\":%zu}",
                            first ? "" : ",", frequency, level_db, input_energy, output_energy,
                            peak, changed, clipped, measured);
                first = false;
            }
        }
        std::puts("]}");
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "SoundBooster probe failed: %s\n", error.what());
        return 1;
    }
}
