#pragma once

#ifdef __linux__
#include <sys/sysmacros.h>
#endif

namespace soundbooster_blocks {
constexpr size_t states = 3;
constexpr uint64_t header_bytes = 16 + states * 64;

uint64_t number(const Bytes& data, size_t offset) {
    require(offset + 8 <= data.size(), "Truncated block bundle");
    uint64_t result = 0;
    for (size_t i = 0; i < 8; ++i) result |= uint64_t(data[offset + i]) << (8 * i);
    return result;
}

std::string hash_text(const Bytes& data, size_t offset) {
    require(offset + 64 <= data.size(), "Truncated bundle hash");
    const std::string result(data.begin() + offset, data.begin() + offset + 64);
    require(std::all_of(result.begin(), result.end(), [](char value) {
        return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
    }), "Invalid SHA256 in block bundle");
    return result;
}

struct Record {
    std::array<std::string, states> hashes;
    std::array<Bytes, states> bytes;
    bool changed;
};

Record record(int bundle, uint64_t& offset, uint64_t length) {
    require(offset <= length && states * 64 <= length - offset, "Truncated block record");
    const Bytes header = read_at(bundle, offset, states * 64);
    offset += states * 64;
    Record result{};
    for (size_t state = 0; state < states; ++state) result.hashes[state] = hash_text(header, state * 64);
    result.changed = result.hashes[0] != result.hashes[1] || result.hashes[0] != result.hashes[2];
    if (result.changed) {
        for (size_t state = 0; state < states; ++state) {
            size_t previous = 0;
            while (previous < state && result.hashes[previous] != result.hashes[state]) ++previous;
            if (previous != state) {
                result.bytes[state] = result.bytes[previous];
                continue;
            }
            require(offset <= length && BLOCK <= length - offset, "Truncated block payload");
            result.bytes[state] = read_at(bundle, offset, BLOCK);
            offset += BLOCK;
            require(hash_bytes(result.bytes[state]) == result.hashes[state], "Corrupt block payload");
        }
    }
    return result;
}

void require_vendor_mapping(int fd) {
#ifdef __linux__
    struct stat status{};
    require(fstat(fd, &status) == 0, "Cannot identify vendor mapping");
    std::ifstream name("/sys/dev/block/" + std::to_string(major(status.st_rdev)) + ":" +
                       std::to_string(minor(status.st_rdev)) + "/dm/name");
    std::string value;
    require(name.good() && std::getline(name, value) && value == "vendor",
            "Only the logical vendor mapping is supported; never write physical super");
    require(capture({"/system/bin/getprop", "ro.product.device"}) == "gta4xlwifi\n",
            "Wrong recovery device");
    struct stat recovery{};
    require(stat("/system/bin/recovery", &recovery) == 0 && S_ISREG(recovery.st_mode),
            "Recovery execution required");
#else
    (void)fd;
    throw std::runtime_error("Recovery device mode requires Android");
#endif
}

void run(const std::string& operation, const std::string& kind, const fs::path& target_path,
         const fs::path& bundle_path, const std::string& expected_bundle, const fs::path& boot) {
    require(operation == "blocks-preflight" || operation == "blocks-apply" ||
            operation == "blocks-restore", "Unknown block operation");
    require(kind == "--file" || kind == "--device", "Explicit target type required");
    const bool regular = kind == "--file";
    const bool write = operation != "blocks-preflight";
    const size_t desired = operation == "blocks-restore" ? 0 : 2;
    FD bundle(open(bundle_path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK));
    struct stat bundle_status{};
    require(fstat(bundle.value, &bundle_status) == 0 && S_ISREG(bundle_status.st_mode) &&
            bundle_status.st_size >= static_cast<off_t>(header_bytes) &&
            bundle_status.st_size <= static_cast<off_t>(2 * MAX_IMAGE), "Invalid bundle file");
    require(flock(bundle.value, LOCK_SH | LOCK_NB) == 0, "Bundle is locked");
    const uint64_t bundle_size = bundle_status.st_size;
    require(image_hash(bundle.value, bundle_size) == expected_bundle, "Block bundle SHA256 mismatch");
    const Bytes header = read_at(bundle.value, 0, header_bytes);
    require(std::string(header.begin(), header.begin() + 8) == "SB3BLK01", "Unknown block bundle version");
    const uint64_t size = number(header, 8);
    require(size >= BLOCK && size <= MAX_IMAGE && size % BLOCK == 0, "Invalid bundle image size");
    std::array<std::string, states> expected;
    for (size_t state = 0; state < states; ++state) expected[state] = hash_text(header, 16 + state * 64);

    check_boot(boot);
    FD target(open(target_path.c_str(), (write ? O_RDWR | O_SYNC : O_RDONLY) |
                   O_CLOEXEC | (regular ? O_NOFOLLOW : 0) | O_NONBLOCK));
    require(flock(target.value, LOCK_EX | LOCK_NB) == 0, "Target is locked");
    struct stat target_status{};
    require(fstat(target.value, &target_status) == 0 &&
            (target_status.st_dev != bundle_status.st_dev || target_status.st_ino != bundle_status.st_ino),
            "Target aliases block bundle");
    require(image_size(target.value, regular) == size, "Vendor size differs; no resizing allowed");
    if (!regular) {
        require_vendor_mapping(target.value);
        require_unmounted(target.value);
    }
    std::array<picosha2::hash256_one_by_one, states> reconstructed;
    picosha2::hash256_one_by_one current_hash;
    uint64_t cursor = header_bytes;
    for (uint64_t offset = 0; offset < size; offset += BLOCK) {
        Record block = record(bundle.value, cursor, bundle_size);
        const Bytes current = read_at(target.value, offset, BLOCK);
        const std::string actual = hash_bytes(current);
        require(std::find(block.hashes.begin(), block.hashes.end(), actual) != block.hashes.end(),
                "Unknown/torn vendor block at " + std::to_string(offset) +
                "; no writes. Stay in recovery; do not boot or force a flash.");
        current_hash.process(current.begin(), current.end());
        for (size_t state = 0; state < states; ++state) {
            const Bytes& payload = block.changed ? block.bytes[state] : current;
            reconstructed[state].process(payload.begin(), payload.end());
        }
    }
    require(cursor == bundle_size, "Trailing data in block bundle");
    for (size_t state = 0; state < states; ++state) {
        reconstructed[state].finish();
        require(picosha2::get_hash_hex_string(reconstructed[state]) == expected[state],
                "Whole-image reconstruction mismatch; no writes");
    }
    current_hash.finish();
    const std::string initial = picosha2::get_hash_hex_string(current_hash);
    require(operation == "blocks-restore" ||
            std::find(expected.begin(), expected.end(), initial) != expected.end(),
            "Mixed/partial install state; use SoundBooster RESTORE first");
    require(image_hash(bundle.value, bundle_size) == expected_bundle, "Bundle changed during preflight");
    require(image_hash(target.value, size) == initial, "Vendor changed during preflight");
    if (!write) {
        std::cout << "SOUNDBOOSTER PREFLIGHT OK: full vendor and boot verified; no partition writes\n";
        return;
    }
    if (initial == expected[desired]) {
        std::cout << "SOUNDBOOSTER ALREADY APPLIED: desired whole-image SHA256 verified\n";
        return;
    }
    if (!regular) require_unmounted(target.value);
    cursor = header_bytes;
    for (uint64_t offset = 0; offset < size; offset += BLOCK) {
        Record block = record(bundle.value, cursor, bundle_size);
        if (!block.changed) continue;
        const std::string actual = hash_bytes(read_at(target.value, offset, BLOCK));
        require(std::find(block.hashes.begin(), block.hashes.end(), actual) != block.hashes.end(),
                "Vendor changed after preflight; stay in recovery and use RESTORE");
        if (actual != block.hashes[desired]) write_at(target.value, offset, block.bytes[desired]);
    }
    require(fsync(target.value) == 0, "Sync failed; stay in recovery and use RESTORE");
    require(image_hash(target.value, size) == expected[desired],
            "Whole vendor read-back failed; stay in recovery and use RESTORE");
    std::cout << "SOUNDBOOSTER " << (desired == 0 ? "RESTORE" : "INSTALL")
              << " VERIFIED: whole vendor SHA256 " << expected[desired] << "\n";
}
}
