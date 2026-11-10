#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef __linux__
#include <linux/fs.h>
#include <sys/ioctl.h>
#endif
#include <lz4.h>
#include <lz4hc.h>
#include <zlib.h>
#include "picosha2.h"

namespace fs = std::filesystem;
using Bytes = std::vector<unsigned char>;
constexpr uint64_t BLOCK = 4096;
constexpr uint64_t MAX_IMAGE = 2ULL * 1024 * 1024 * 1024;
const std::array<std::string, 3> paths = {
    "/etc/audio_policy_volumes.xml",
    "/etc/audio_policy_engine_stream_volumes.xml",
    "/etc/dolby/dax-default.xml",
};

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

class FD {
public:
    int value;
    explicit FD(int fd) : value(fd) { require(fd >= 0, "open/pipe failed: " + std::string(strerror(errno))); }
    ~FD() { close(value); }
    FD(const FD&) = delete;
    FD& operator=(const FD&) = delete;
};

Bytes read_at(int fd, uint64_t offset, size_t size) {
    Bytes result(size);
    size_t done = 0;
    while (done < size) {
        ssize_t count = pread(fd, result.data() + done, size - done, offset + done);
        if (count < 0 && errno == EINTR) continue;
        require(count > 0, "Short/failed read at " + std::to_string(offset + done));
        done += static_cast<size_t>(count);
    }
    return result;
}

void write_at(int fd, uint64_t offset, const Bytes& data) {
    size_t done = 0;
    while (done < data.size()) {
        ssize_t count = pwrite(fd, data.data() + done, data.size() - done, offset + done);
        if (count < 0 && errno == EINTR) continue;
        require(count > 0, "Write failed. Stay in recovery and apply adaptive RESTORE.");
        done += static_cast<size_t>(count);
    }
}

Bytes load(const fs::path& path, size_t maximum = 1024 * 1024) {
    FD fd(open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW));
    struct stat status {};
    require(fstat(fd.value, &status) == 0 && S_ISREG(status.st_mode), "Expected regular file: " + path.string());
    require(status.st_size > 0 && static_cast<uint64_t>(status.st_size) <= maximum, "File size out of bounds");
    return read_at(fd.value, 0, status.st_size);
}

std::string hash_bytes(const Bytes& data) {
    return picosha2::hash256_hex_string(data.begin(), data.end());
}

std::string capture(const std::vector<std::string>& arguments, size_t maximum = 1024 * 1024) {
    int handles[2];
    require(pipe(handles) == 0, "pipe failed");
    FD input(handles[0]);
    pid_t pid = fork();
    require(pid >= 0, "fork failed");
    if (pid == 0) {
        close(handles[0]);
        if (dup2(handles[1], STDOUT_FILENO) < 0) _exit(126);
        close(handles[1]);
        std::vector<char*> argv;
        for (const auto& argument : arguments) argv.push_back(const_cast<char*>(argument.c_str()));
        argv.push_back(nullptr);
        execv(argv[0], argv.data());
        _exit(127);
    }
    close(handles[1]);
    std::string result;
    char buffer[8192];
    bool overflow = false;
    for (;;) {
        ssize_t size = read(input.value, buffer, sizeof(buffer));
        if (size < 0 && errno == EINTR) continue;
        require(size >= 0, "subprocess pipe read failed");
        if (!size) break;
        if (result.size() + size > maximum) overflow = true;
        if (!overflow) result.append(buffer, size);
    }
    int status = 0;
    require(waitpid(pid, &status, 0) == pid, "waitpid failed");
    require(!overflow, "Subprocess output too large");
    require(WIFEXITED(status) && WEXITSTATUS(status) == 0, "Tool failed: " + arguments[0]);
    return result;
}

uint64_t image_size(int fd, bool regular) {
    struct stat status {};
    require(fstat(fd, &status) == 0, "fstat failed");
    uint64_t size = 0;
    if (regular) {
        require(S_ISREG(status.st_mode), "--file requires a regular image, never a block device");
        size = status.st_size;
    } else {
        require(S_ISBLK(status.st_mode), "--device requires a block device");
#ifdef __linux__
        require(ioctl(fd, BLKGETSIZE64, &size) == 0, "Cannot read block-device size");
#else
        throw std::runtime_error("Device mode is Linux/Android only");
#endif
    }
    require(size >= BLOCK && size <= MAX_IMAGE && size % BLOCK == 0, "Unsupported image size/alignment");
    return size;
}

void require_unmounted(int fd) {
#ifdef __linux__
    struct stat target {};
    require(fstat(fd, &target) == 0, "Cannot stat target");
    std::ifstream mounts("/proc/mounts");
    require(mounts.good(), "Cannot inspect mounted filesystems");
    std::string line;
    while (std::getline(mounts, line)) {
        std::istringstream parser(line);
        std::string source;
        parser >> source;
        if (source.empty() || source.front() != '/') continue;
        struct stat entry {};
        if (stat(source.c_str(), &entry) == 0 && S_ISBLK(entry.st_mode)) {
            require(entry.st_rdev != target.st_rdev, "Target is mounted; refusing raw writes");
        }
    }
#else
    (void)fd;
    throw std::runtime_error("Device mode is Linux/Android only");
#endif
}

struct Change {
    uint64_t offset;
    Bytes before;
    Bytes after;
};

std::string image_hash(int fd, uint64_t size, const std::vector<Change>& substitutions = {},
                       bool use_after = false) {
    picosha2::hash256_one_by_one hasher;
    for (uint64_t offset = 0; offset < size; offset += 1024 * 1024) {
        Bytes data = read_at(fd, offset, std::min<uint64_t>(1024 * 1024, size - offset));
        for (const auto& change : substitutions) {
            if (change.offset >= offset && change.offset < offset + data.size()) {
                const Bytes& replacement = use_after ? change.after : change.before;
                require(change.offset + replacement.size() <= offset + data.size(), "Invalid substitution boundary");
                std::copy(replacement.begin(), replacement.end(), data.begin() + change.offset - offset);
            }
        }
        hasher.process(data.begin(), data.end());
    }
    hasher.finish();
    return picosha2::get_hash_hex_string(hasher);
}

class TemporaryImage {
public:
    fs::path path;
    explicit TemporaryImage(const fs::path& directory) {
        std::string pattern = (directory / "audio-image-XXXXXX").string();
        std::vector<char> name(pattern.begin(), pattern.end());
        name.push_back(0);
        FD fd(mkstemp(name.data()));
        path = name.data();
    }
    ~TemporaryImage() { unlink(path.c_str()); }
};

void copy_image(int source, uint64_t size, const fs::path& path) {
    struct statvfs space {};
    require(statvfs(path.parent_path().c_str(), &space) == 0, "Cannot inspect temporary space");
    require(static_cast<uint64_t>(space.f_bavail) * space.f_frsize >= size + 8 * 1024 * 1024,
            "Insufficient temporary space; no partition writes");
    FD output(open(path.c_str(), O_WRONLY | O_TRUNC | O_CLOEXEC | O_NOFOLLOW));
    for (uint64_t offset = 0; offset < size; offset += 1024 * 1024) {
        write_at(output.value, offset, read_at(source, offset, std::min<uint64_t>(1024 * 1024, size - offset)));
    }
    require(fsync(output.value) == 0, "Cannot sync temporary image");
}

Bytes decode(const Bytes& cluster, size_t expected) {
    auto start = std::find_if(cluster.begin(), cluster.end(), [](unsigned char value) { return value != 0; });
    require(start != cluster.end(), "Empty LZ4 cluster");
    Bytes result(expected);
    int size = LZ4_decompress_safe(reinterpret_cast<const char*>(&*start),
        reinterpret_cast<char*>(result.data()), cluster.end() - start, expected);
    require(size == static_cast<int>(expected), "LZ4 cluster does not decode to the expected file");
    return result;
}

Bytes encode(const Bytes& content) {
    Bytes compressed(BLOCK);
    int size = LZ4_compress_HC(reinterpret_cast<const char*>(content.data()),
        reinterpret_cast<char*>(compressed.data()), content.size(), BLOCK, 12);
    require(size > 0, "Modified XML does not fit its original pcluster; no partition writes");
    Bytes cluster(BLOCK, 0);
    std::copy_n(compressed.begin(), size, cluster.end() - size);
    require(decode(cluster, content.size()) == content, "LZ4 round-trip failed");
    return cluster;
}

uint32_t little32(const Bytes& data, size_t offset) {
    require(offset + 4 <= data.size(), "Truncated binary header");
    return static_cast<uint32_t>(data[offset]) |
        (static_cast<uint32_t>(data[offset + 1]) << 8) |
        (static_cast<uint32_t>(data[offset + 2]) << 16) |
        (static_cast<uint32_t>(data[offset + 3]) << 24);
}

void check_boot(const fs::path& path) {
    FD fd(open(path.c_str(), O_RDONLY | O_CLOEXEC));
    Bytes header = read_at(fd.value, 0, 2048);
    require(std::string(header.begin(), header.begin() + 8) == "ANDROID!", "Unsupported boot image");
    require(little32(header, 40) <= 2, "Unsupported boot header");
    uint32_t page = little32(header, 36), kernel = little32(header, 8), ramdisk_size = little32(header, 16);
    require(page == 2048 || page == 4096 || page == 8192 || page == 16384, "Unsupported boot page size");
    require(ramdisk_size > 0 && ramdisk_size <= 64 * 1024 * 1024, "Invalid ramdisk size");
    uint64_t offset = page + ((static_cast<uint64_t>(kernel) + page - 1) / page) * page;
    Bytes compressed = read_at(fd.value, offset, ramdisk_size);
    Bytes ramdisk(128 * 1024 * 1024);
    z_stream stream {};
    require(inflateInit2(&stream, 15 + 16) == Z_OK, "gzip init failed");
    stream.next_in = compressed.data();
    stream.avail_in = compressed.size();
    stream.next_out = ramdisk.data();
    stream.avail_out = ramdisk.size();
    int status = inflate(&stream, Z_FINISH);
    size_t length = stream.total_out;
    inflateEnd(&stream);
    require(status == Z_STREAM_END && length > 0, "Unsupported/truncated boot ramdisk");
    ramdisk.resize(length);
    bool found = false, trailer = false;
    size_t position = 0;
    while (position + 110 <= ramdisk.size()) {
        std::string record(ramdisk.begin() + position, ramdisk.begin() + position + 110);
        require(record.substr(0, 6) == "070701", "Unsupported cpio header");
        size_t size = std::stoul(record.substr(54, 8), nullptr, 16);
        size_t name_length = std::stoul(record.substr(94, 8), nullptr, 16);
        require(name_length > 0 && name_length < 4096 && position + 110 + name_length <= length,
                "Invalid cpio name");
        std::string name(ramdisk.begin() + position + 110,
                         ramdisk.begin() + position + 110 + name_length - 1);
        position = (position + 110 + name_length + 3) & ~size_t(3);
        require(position <= length && size <= length - position, "Truncated cpio entry");
        if (name == "TRAILER!!!") {
            trailer = true;
            break;
        }
        if (name.find("fstab") != std::string::npos) {
            std::string text(ramdisk.begin() + position, ramdisk.begin() + position + size);
            std::istringstream lines(text);
            std::string line;
            while (std::getline(lines, line)) {
                std::istringstream fields(line);
                std::string device, mount, type, options, flags;
                if (!(fields >> device >> mount >> type >> options >> flags)) continue;
                if (mount == "/vendor") {
                    found = true;
                    require(device == "vendor" && flags.find("logical") != std::string::npos &&
                            flags.find("first_stage_mount") != std::string::npos,
                            "Unsupported vendor fstab mapping");
                    require(flags.find("avb") == std::string::npos &&
                            flags.find("verify") == std::string::npos,
                            "Vendor verification enabled in boot fstab; AVB will not be modified");
                }
            }
        }
        position = (position + size + 3) & ~size_t(3);
    }
    require(found && trailer, "Missing vendor fstab or complete cpio trailer in boot ramdisk");
    std::cout << "BOOT CHECK OK: logical vendor without AVB flags in boot ramdisk\n";
}

std::vector<Change> prepare(int fd, uint64_t size, const fs::path& image, const fs::path& root) {
    Bytes superblock = read_at(fd, 1024, 128);
    require(little32(superblock, 0) == 0xe0f5e1e2, "Vendor is not EROFS");
    require(superblock[12] == 12, "Only 4 KiB EROFS blocks are supported");
    require((little32(superblock, 80) & ~1U) == 0, "Unsupported EROFS incompatible features");
    capture({(root / "bin/fsck.erofs").string(), "--extract", image.string()});
    std::vector<Change> result;
    int originals = 0, patched = 0;
    for (size_t index = 0; index < paths.size(); ++index) {
        Bytes original = load(root / "templates" / (std::to_string(index) + ".original"));
        Bytes replacement = load(root / "templates" / (std::to_string(index) + ".patched"));
        require(original.size() == replacement.size(), "Template decoded lengths differ");
        std::string content = capture({(root / "bin/dump.erofs").string(), "--cat",
                                       "--path=" + paths[index], image.string()});
        Bytes actual(content.begin(), content.end());
        bool is_original = actual == original, is_patched = actual == replacement;
        require(is_original || is_patched, "Unrecognized audio configuration: " + paths[index] +
                ". New tuning requires review; no partition writes");
        originals += is_original;
        patched += is_patched;
        std::string layout = capture({(root / "bin/dump.erofs").string(), "-e",
                                      "--path=" + paths[index], image.string()});
        std::regex extent(R"(\s0:\s+0\.\.\s+([0-9]+)\s+\|\s+([0-9]+)\s+:\s+([0-9]+)\.\.\s+([0-9]+)\s+\|\s+([0-9]+))");
        std::smatch match;
        require(std::regex_search(layout, match, extent) &&
                layout.find("1 extents found") != std::string::npos &&
                layout.find("Layout: 3") != std::string::npos &&
                layout.find("Links: 1 ") != std::string::npos, "Unsupported inode/extent layout: " + paths[index]);
        uint64_t offset = std::stoull(match[3]), end = std::stoull(match[4]);
        require(std::stoull(match[1]) == actual.size() && std::stoull(match[2]) == actual.size() &&
                std::stoull(match[5]) == BLOCK && offset % BLOCK == 0 &&
                end == offset + BLOCK && end <= size, "Unsupported extent geometry");
        for (const auto& previous : result) require(previous.offset != offset, "Overlapping audio clusters");
        Bytes cluster = read_at(fd, offset, BLOCK);
        require(decode(cluster, actual.size()) == actual, "Extent is not an independent LZ4 cluster");
        result.push_back({offset, cluster, is_patched ? cluster : encode(replacement)});
    }
    require(originals == 3 || patched == 3, "Mixed/partial audio preset detected; restore first");
    if (patched == 3) {
        std::cout << "ALREADY APPLIED: recognized preset; attenuation will not be stacked\n";
        return {};
    }
    {
        FD output(open(image.c_str(), O_RDWR | O_CLOEXEC | O_NOFOLLOW));
        for (const auto& change : result) write_at(output.value, change.offset, change.after);
        require(fsync(output.value) == 0, "Cannot sync staged image");
    }
    capture({(root / "bin/fsck.erofs").string(), "--extract", image.string()});
    for (size_t index = 0; index < paths.size(); ++index) {
        std::string content = capture({(root / "bin/dump.erofs").string(), "--cat",
                                      "--path=" + paths[index], image.string()});
        require(Bytes(content.begin(), content.end()) == load(root / "templates" / (std::to_string(index) + ".patched")),
                "Staged EROFS file verification failed");
    }
    return result;
}

void append_u64(Bytes& bytes, uint64_t number) {
    for (int index = 0; index < 8; ++index) bytes.push_back((number >> (8 * index)) & 255);
}

void append_string(Bytes& bytes, const std::string& text) {
    bytes.insert(bytes.end(), text.begin(), text.end());
}

struct Backup {
    uint64_t size;
    std::string original_hash;
    std::string patched_hash;
    std::vector<Change> changes;
};

Bytes serialize(const Backup& backup) {
    Bytes bytes;
    append_string(bytes, "AUDADP01");
    append_u64(bytes, backup.size);
    append_string(bytes, backup.original_hash);
    append_string(bytes, backup.patched_hash);
    require(backup.changes.size() == 3, "Backup must contain exactly three clusters");
    for (const auto& change : backup.changes) {
        append_u64(bytes, change.offset);
        bytes.insert(bytes.end(), change.before.begin(), change.before.end());
        bytes.insert(bytes.end(), change.after.begin(), change.after.end());
    }
    append_string(bytes, hash_bytes(bytes));
    return bytes;
}

Backup deserialize(const Bytes& bytes) {
    constexpr size_t length = 8 + 8 + 128 + 3 * (8 + 2 * BLOCK) + 64;
    require(bytes.size() == length && std::string(bytes.begin(), bytes.begin() + 8) == "AUDADP01",
            "Invalid backup header/size");
    Bytes payload(bytes.begin(), bytes.end() - 64);
    require(hash_bytes(payload) == std::string(bytes.end() - 64, bytes.end()), "Backup checksum mismatch");
    size_t position = 8;
    auto integer = [&]() {
        uint64_t value = 0;
        for (int index = 0; index < 8; ++index) value |= static_cast<uint64_t>(bytes.at(position++)) << (8 * index);
        return value;
    };
    auto text = [&](size_t count) {
        std::string value(bytes.begin() + position, bytes.begin() + position + count);
        position += count;
        return value;
    };
    Backup result {integer(), text(64), text(64), {}};
    require(result.size >= BLOCK && result.size <= MAX_IMAGE && result.size % BLOCK == 0, "Invalid backup image size");
    require(std::regex_match(result.original_hash, std::regex("[0-9a-f]{64}")) &&
            std::regex_match(result.patched_hash, std::regex("[0-9a-f]{64}")), "Invalid backup digest");
    for (int index = 0; index < 3; ++index) {
        uint64_t offset = integer();
        require(offset % BLOCK == 0 && offset >= BLOCK && offset <= result.size - BLOCK, "Invalid backup offset");
        for (const auto& previous : result.changes) require(previous.offset != offset, "Overlapping backup offsets");
        Bytes original(bytes.begin() + position, bytes.begin() + position + BLOCK);
        position += BLOCK;
        Bytes patched(bytes.begin() + position, bytes.begin() + position + BLOCK);
        position += BLOCK;
        result.changes.push_back({offset, original, patched});
    }
    return result;
}

void save_backup(const fs::path& directory, const Backup& backup, bool regular) {
    if (!regular) {
        require(directory.string() == "/cache/lineage-audio-adaptive", "Persistent backup must use /cache/lineage-audio-adaptive");
        struct stat cache {};
        require(lstat("/cache", &cache) == 0 && S_ISDIR(cache.st_mode), "Cache directory missing");
        std::ifstream mounts("/proc/mounts");
        std::string line;
        bool mounted = false;
        while (std::getline(mounts, line)) {
            std::istringstream fields(line);
            std::string source, point, type;
            fields >> source >> point >> type;
            if (point == "/cache" && type == "ext4" && source.rfind("/dev/block/", 0) == 0) mounted = true;
        }
        require(mounted, "Persistent ext4 /cache is not mounted; no writes to vendor");
    }
    if (!fs::exists(directory)) require(mkdir(directory.c_str(), 0700) == 0, "Cannot create backup directory");
    struct stat status {};
    require(lstat(directory.c_str(), &status) == 0 && S_ISDIR(status.st_mode) && !S_ISLNK(status.st_mode),
            "Unsafe backup directory");
    Bytes bytes = serialize(backup);
    fs::path target = directory / (backup.original_hash + ".bak");
    if (fs::exists(target)) {
        require(load(target) == bytes, "Existing backup differs; no partition writes");
        return;
    }
    FD output(open(target.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600));
    write_at(output.value, 0, bytes);
    require(fsync(output.value) == 0, "Cannot persist backup; no partition writes");
    FD parent(open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC));
    require(fsync(parent.value) == 0 && load(target) == bytes, "Backup verification failed; no partition writes");
    std::cout << "BACKUP VERIFIED: " << target << "\n";
}

void apply_changes(int fd, const Backup& backup, bool restore) {
    for (const auto& change : backup.changes) write_at(fd, change.offset, restore ? change.before : change.after);
    require(fsync(fd) == 0, "Vendor sync failed; use adaptive RESTORE");
    for (const auto& change : backup.changes) {
        require(read_at(fd, change.offset, BLOCK) == (restore ? change.before : change.after),
                "Vendor cluster read-back failed; use adaptive RESTORE");
    }
    require(image_hash(fd, backup.size) == (restore ? backup.original_hash : backup.patched_hash),
            "Whole vendor SHA256 read-back failed; use adaptive RESTORE");
}

void restore_image(int fd, uint64_t size, const fs::path& directory) {
    require(fs::is_directory(directory), "Backup directory is unavailable; no partition writes");
    std::vector<Backup> candidates;
    for (const auto& entry : fs::directory_iterator(directory)) {
        if (entry.path().extension() != ".bak") continue;
        Backup backup = deserialize(load(entry.path()));
        if (backup.size != size) continue;
        if (image_hash(fd, size, backup.changes) == backup.original_hash) candidates.push_back(backup);
    }
    require(candidates.size() == 1, "No unique backup matches this vendor outside the audio clusters; no writes");
    Backup& backup = candidates.front();
    require(image_hash(fd, size, backup.changes, true) == backup.patched_hash, "Backup patched-image identity mismatch");
    apply_changes(fd, backup, true);
    std::cout << "RESTORE VERIFIED: original vendor SHA256 " << backup.original_hash << "\n";
}

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "selftest") {
            Bytes abc {'a', 'b', 'c'};
            require(hash_bytes(abc) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                    "SHA256 known-answer test failed");
            Bytes content(10000, 'a');
            require(decode(encode(content), content.size()) == content, "LZ4 selftest failed");
            std::cout << "SELFTEST OK\n";
            return 0;
        }
        if (argc == 3 && std::string(argv[1]) == "checkboot") {
            check_boot(argv[2]);
            return 0;
        }
        require(argc == 7, "Usage: audio-adaptive preflight|apply|restore --file|--device IMAGE BACKUPS TOOLS TMP");
        std::string mode = argv[1], kind = argv[2];
        require(mode == "preflight" || mode == "apply" || mode == "restore", "Unknown operation");
        require(kind == "--file" || kind == "--device", "Explicit target type required");
        bool regular = kind == "--file";
        bool write = mode != "preflight";
        FD target(open(argv[3], (write ? O_RDWR | O_SYNC : O_RDONLY) | O_CLOEXEC));
        require(flock(target.value, LOCK_EX | LOCK_NB) == 0, "Another process has locked this image");
        uint64_t size = image_size(target.value, regular);
        if (!regular) require_unmounted(target.value);
        if (mode == "restore") {
            restore_image(target.value, size, argv[4]);
            return 0;
        }
        TemporaryImage image(argv[6]);
        copy_image(target.value, size, image.path);
        std::string original_hash = image_hash(target.value, size);
        std::vector<Change> changes = prepare(target.value, size, image.path, argv[5]);
        if (changes.empty()) return 0;
        FD staged(open(image.path.c_str(), O_RDONLY | O_CLOEXEC));
        std::string patched_hash = image_hash(staged.value, size);
        require(image_hash(target.value, size, changes, true) == patched_hash, "Staging changed bytes outside the intended clusters");
        require(image_hash(target.value, size) == original_hash, "Source image changed during staging");
        Backup backup {size, original_hash, patched_hash, changes};
        if (!write) {
            std::cout << "PREFLIGHT OK: compatible audio XML and dynamic offsets; no vendor writes\n";
            return 0;
        }
        save_backup(argv[4], backup, regular);
        require(image_hash(target.value, size) == original_hash, "Vendor changed after backup; no partition writes");
        if (!regular) require_unmounted(target.value);
        apply_changes(target.value, backup, false);
        std::cout << "INSTALL VERIFIED: three current-vendor clusters updated; SHA256 " << patched_hash << "\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "AUDIO ERROR: " << error.what() << "\n";
        return 1;
    }
}
