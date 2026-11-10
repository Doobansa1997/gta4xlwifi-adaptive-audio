#include "picosha2.h"

extern "C" {
#include "fec.h"
}

#include <algorithm>
#include <array>
#include <charconv>
#include <cstdint>
#include <fcntl.h>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

namespace {
constexpr uint64_t block = 4096;
constexpr uint64_t roots = 2;
constexpr uint64_t symbols = 255 - roots;
constexpr uint64_t maximum = 1024ULL * 1024 * 1024;
constexpr size_t header_size = 60;

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
struct File {
    int fd;
    explicit File(int value) : fd(value) { require(fd >= 0, "Cannot open regular file"); }
    ~File() { close(fd); }
    File(const File&) = delete;
    File& operator=(const File&) = delete;
};
struct Geometry {
    uint64_t rounds;
    uint64_t parity;
};
Geometry geometry(uint64_t size) {
    require(size && size <= maximum && size % block == 0,
            "Only nonempty, 4096-aligned raw images up to 1 GiB are supported");
    const uint64_t rounds = (size / block + symbols - 1) / symbols;
    return {rounds, rounds * roots * block};
}
uint64_t number(const std::string& value) {
    uint64_t result = 0;
    const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
    require(parsed.ec == std::errc{} && parsed.ptr == value.data() + value.size(),
            "Invalid unsigned decimal image size");
    return result;
}
void write_all(int fd, const unsigned char* bytes, size_t size) {
    while (size) {
        const ssize_t count = write(fd, bytes, size);
        require(count > 0, "Cannot write FEC output");
        bytes += count;
        size -= count;
    }
}
void little_endian(std::array<unsigned char, block>& bytes, size_t offset, uint64_t value, size_t size) {
    for (size_t i = 0; i < size; ++i) bytes[offset + i] = (value >> (8 * i)) & 255;
}
void encode(const char* input_path, const char* output_path) {
    File input(open(input_path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK));
    struct stat input_stat{};
    require(fstat(input.fd, &input_stat) == 0 && S_ISREG(input_stat.st_mode),
            "Input must be a regular, non-symlink raw image");
    const auto layout = geometry(input_stat.st_size);
    std::vector<unsigned char> data(input_stat.st_size);
    size_t read_bytes = 0;
    while (read_bytes < data.size()) {
        const ssize_t count = read(input.fd, data.data() + read_bytes, data.size() - read_bytes);
        require(count > 0, "Cannot read complete FEC input");
        read_bytes += count;
    }
    unsigned char extra;
    require(read(input.fd, &extra, 1) == 0, "Input size changed");
    std::vector<unsigned char> parity(layout.parity);
    std::unique_ptr<void, decltype(&free_rs_char)> codec(
        init_rs_char(8, 0x11d, 0, 1, roots, 0), free_rs_char);
    require(codec != nullptr, "Cannot initialize original Android RS codec");
    // Android fec/ecc.h interleaves each RS symbol in rounds * 4096-byte strides.
    const uint64_t stride = layout.rounds * block;
    std::array<unsigned char, symbols> word{};
    for (uint64_t i = 0; i < stride; ++i) {
        for (size_t j = 0; j < word.size(); ++j) {
            const uint64_t offset = i + j * stride;
            word[j] = offset < data.size() ? data[offset] : 0;
        }
        encode_rs_char(codec.get(), word.data(), parity.data() + i * roots);
    }
    std::array<unsigned char, block> header{};
    little_endian(header, 0, 0xFECFECFE, 4);
    little_endian(header, 4, 0, 4);
    little_endian(header, 8, header_size, 4);
    little_endian(header, 12, roots, 4);
    little_endian(header, 16, parity.size(), 4);
    little_endian(header, 20, data.size(), 8);
    picosha2::hash256(parity.begin(), parity.end(), header.begin() + 28, header.begin() + header_size);
    std::copy_n(header.begin(), header_size, header.end() - header_size);

    File output(open(output_path, O_WRONLY | O_CREAT | O_NOFOLLOW | O_NONBLOCK, 0600));
    struct stat output_stat{};
    require(fstat(output.fd, &output_stat) == 0 && S_ISREG(output_stat.st_mode),
            "Output must be a regular, non-symlink file");
    require(input_stat.st_dev != output_stat.st_dev || input_stat.st_ino != output_stat.st_ino,
            "Input and output must be distinct files");
    require(ftruncate(output.fd, 0) == 0, "Cannot truncate output");
    write_all(output.fd, parity.data(), parity.size());
    write_all(output.fd, header.data(), header.size());
    require(fsync(output.fd) == 0, "Cannot sync FEC output");
}
}

int main(int argc, char** argv) {
    try {
        require(argc == 5 || argc == 6,
                "Encode-only Android FEC adapter: --print-fec-size SIZE --roots 2 | --encode --roots 2 INPUT OUTPUT");
        if (argc == 5) {
            require(std::string(argv[1]) == "--print-fec-size" &&
                    std::string(argv[3]) == "--roots" && std::string(argv[4]) == "2",
                    "Only two-root size calculation is supported");
            std::cout << geometry(number(argv[2])).parity + block << "\n";
            require(std::cout.good(), "Cannot write FEC size");
        } else {
            require(std::string(argv[1]) == "--encode" &&
                    std::string(argv[2]) == "--roots" && std::string(argv[3]) == "2",
                    "Only two-root raw-image encoding is supported; decode is not implemented");
            encode(argv[4], argv[5]);
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FEC encode error: " << error.what() << "\n";
        return 1;
    }
}
