#include "erofs/dir.h"
#include "erofs/io.h"
#include "picosha2.h"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstring>
#include <exception>
#include <fcntl.h>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <vector>

namespace {
erofs_sb_info filesystem{};
std::set<erofs_nid_t> directories;
size_t entries = 0;
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
std::string hex(const char* data, size_t size) {
    static constexpr char digits[] = "0123456789abcdef";
    std::string result;
    for (size_t i = 0; i < size; ++i) {
        const auto value = static_cast<unsigned char>(data[i]);
        result += digits[value >> 4];
        result += digits[value & 15];
    }
    return result;
}
void visit(erofs_nid_t nid, const std::string& path, size_t depth);
struct Directory {
    erofs_dir_context context{};
    const std::string* path;
    size_t depth;
    std::exception_ptr error;
};
int child(erofs_dir_context* context) {
    if (context->dot_dotdot) return 0;
    auto& parent = *reinterpret_cast<Directory*>(context);
    try {
        std::string name(context->dname, context->de_namelen);
        require(!name.empty() && name.find('/') == std::string::npos &&
                name.find('\0') == std::string::npos, "Invalid directory name");
        visit(context->de_nid, *parent.path + "/" + name, parent.depth + 1);
    } catch (...) {
        parent.error = std::current_exception();
        return -EIO;
    }
    return 0;
}
void visit(erofs_nid_t nid, const std::string& path, size_t depth) {
    require(depth < 64 && ++entries <= 10000, "Filesystem traversal limit exceeded");
    erofs_inode inode{};
    inode.sbi = &filesystem;
    inode.nid = nid;
    require(erofs_read_inode_from_disk(&inode) == 0, "Cannot read inode");
    std::cout << "{\"path_hex\":\"" << hex(path.data(), path.size()) << "\",\"nid\":" << nid
              << ",\"mode\":" << inode.i_mode << ",\"uid\":" << inode.i_uid
              << ",\"gid\":" << inode.i_gid << ",\"nlink\":" << inode.i_nlink
              << ",\"size\":" << inode.i_size << ",\"mtime\":" << inode.i_mtime
              << ",\"mtime_nsec\":" << inode.i_mtime_nsec << ",\"xattrs\":{";
    const int size = erofs_listxattr(&inode, nullptr, 0);
    require(size >= 0 && size <= 65536, "Invalid xattr list");
    std::vector<char> names(size);
    if (size) require(erofs_listxattr(&inode, names.data(), names.size()) == size, "Cannot list xattrs");
    bool first = true;
    for (size_t offset = 0; offset < names.size();) {
        const char* name = names.data() + offset;
        const auto* end = static_cast<const char*>(std::memchr(name, 0, names.size() - offset));
        require(end && end != name, "Invalid xattr name");
        const int length = erofs_getxattr(&inode, name, nullptr, 0);
        require(length >= 0 && length <= 65536, "Invalid xattr value");
        std::vector<char> value(length);
        require(erofs_getxattr(&inode, name, value.data(), value.size()) == length, "Cannot read xattr");
        if (!first) std::cout << ",";
        first = false;
        std::cout << "\"" << hex(name, end - name) << "\":\"" << hex(value.data(), value.size()) << "\"";
        offset += end - name + 1;
    }
    std::cout << "}";
    if (S_ISREG(inode.i_mode) || S_ISLNK(inode.i_mode)) {
        erofs_vfile file{};
        require(erofs_iopen(&file, &inode) == 0, "Cannot open inode data");
        picosha2::hash256_one_by_one hasher;
        std::array<char, 65536> buffer{};
        for (uint64_t offset = 0; offset < inode.i_size;) {
            size_t length = std::min<uint64_t>(buffer.size(), inode.i_size - offset);
            require(erofs_pread(&file, buffer.data(), length, offset) == 0, "Cannot decode inode data");
            hasher.process(buffer.data(), buffer.data() + length);
            offset += length;
        }
        hasher.finish();
        std::cout << ",\"sha256\":\"" << picosha2::get_hash_hex_string(hasher) << "\"";
    } else {
        require(S_ISDIR(inode.i_mode), "Unsupported special inode");
    }
    std::cout << "}\n";
    if (S_ISDIR(inode.i_mode)) {
        require(directories.insert(nid).second, "Directory cycle or hardlink");
        Directory directory{};
        directory.path = &path;
        directory.depth = depth;
        directory.context.dir = &inode;
        directory.context.cb = child;
        const int result = erofs_iterate_dir(&directory.context, false);
        if (directory.error) std::rethrow_exception(directory.error);
        require(result == 0, "Cannot iterate directory");
    }
    free(inode.xattr_shared_xattrs);
}
}
int main(int argc, char** argv) {
    try {
        require(argc == 2, "Usage: erofs-manifest IMAGE");
        require(erofs_dev_open(&filesystem, argv[1], O_RDONLY) == 0, "Cannot open image");
        require(erofs_read_superblock(&filesystem) == 0, "Cannot read superblock");
        visit(filesystem.root_nid, "", 0);
        std::cout.flush();
        require(std::cout.good(), "Cannot write manifest");
        erofs_dev_close(&filesystem);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "EROFS audit error: " << error.what() << "\n";
        return 1;
    }
}
