#pragma once

#include <cstddef>
#include <cstdint>

// ARM legacy effect API 2.0/library API 3.0 wire layout, not a platform SDK.
namespace sbfx {
struct Uuid {
    uint32_t low;
    uint16_t mid, high, sequence;
    uint8_t node[6];
};
struct Descriptor {
    Uuid type, uuid;
    uint32_t api, flags;
    uint16_t cpu, memory;
    char name[64], implementor[64];
};
struct Buffer { size_t frames; void* raw; };
struct Provider {
    int32_t (*get)(void*, Buffer*);
    int32_t (*release)(void*, Buffer*);
    void* cookie;
};
struct BufferConfig {
    Buffer buffer;
    uint32_t rate, channels;
    Provider provider;
    uint8_t format, access;
    uint16_t mask;
};
struct Config { BufferConfig input, output; };
struct Interface;
using Handle = const Interface**;
struct Interface {
    int32_t (*process)(Handle, Buffer*, Buffer*);
    int32_t (*command)(Handle, uint32_t, uint32_t, void*, uint32_t*, void*);
    int32_t (*descriptor)(Handle, Descriptor*);
    int32_t (*reverse)(Handle, Buffer*, Buffer*);
};
struct Library {
    uint32_t tag, version;
    const char* name;
    const char* implementor;
    int32_t (*create)(const Uuid*, int32_t, int32_t, Handle*);
    int32_t (*release)(Handle);
    int32_t (*descriptor)(const Uuid*, Descriptor*);
};
enum Command : uint32_t {
    Init = 0, SetConfig = 1, Reset = 2, Enable = 3, Disable = 4,
    SetDevice = 9, SetVolume = 10, GetConfig = 14, Dump = 21
};
constexpr uint32_t speaker = 2, unity_volume = 1 << 24;
constexpr uint16_t all_config = 31;
constexpr uint16_t pcm_config = all_config & ~uint16_t(1);
constexpr Uuid implementation{0xd7625a14, 0x10c6, 0x4eed, 0x98a0, {0x32,0x24,0x61,0xab,0x70,0x55}};
constexpr Uuid type{0x638d19e0, 0x44ad, 0x493d, 0x9ca4, {0x51,0x32,0xec,0x67,0x17,0x24}};
static_assert(sizeof(void*) == 4 || sizeof(void*) == 8);
static_assert(sizeof(Uuid) == 16 && sizeof(Descriptor) == 172);
static_assert(sizeof(BufferConfig) == (sizeof(void*) == 8 ? 56 : 32));
static_assert(sizeof(Config) == 2 * sizeof(BufferConfig));
static_assert(offsetof(BufferConfig, format) == (sizeof(void*) == 8 ? 48 : 28));
static_assert(sizeof(Library) == 8 + 5 * sizeof(void*) && sizeof(Interface) == 4 * sizeof(void*));
}
