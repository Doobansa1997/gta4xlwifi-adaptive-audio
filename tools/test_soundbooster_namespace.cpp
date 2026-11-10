#include "../src/soundbooster_effect_abi.h"

#include <android/dlext.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <unistd.h>

namespace {
void require(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "%s\n", message);
        if (const char* error = dlerror()) std::fprintf(stderr, "%s\n", error);
        std::exit(1);
    }
}
}

int main(int argc, char** argv) {
    alarm(30);
    require(argc == 2, "Usage: namespace-test EFFECT");
    void* api = dlopen("libdl_android.so", RTLD_NOW | RTLD_LOCAL);
    require(api, "Cannot load Android namespace API");
    using Create = void* (*)(const char*, const char*, const char*, uint64_t, const char*, void*);
    using Link = bool (*)(void*, void*, const char*);
    auto create = reinterpret_cast<Create>(dlsym(api, "android_create_namespace"));
    auto link = reinterpret_cast<Link>(dlsym(api, "android_link_namespaces"));
    require(create && link, "Cannot resolve Android namespace API");
    void* ns = create("soundbooster-vendor-test", nullptr, "/vendor/lib", 1,
                      "/vendor/lib:/data/local/tmp", nullptr);
    require(ns, "Cannot create isolated vendor namespace");
    require(link(ns, nullptr, "libc.so:libm.so:libdl.so:liblog.so"), "Cannot link system dependencies");
    android_dlextinfo extension{};
    extension.flags = ANDROID_DLEXT_USE_NAMESPACE;
    extension.library_namespace = static_cast<android_namespace_t*>(ns);
    void* library = android_dlopen_ext(argv[1], RTLD_NOW | RTLD_LOCAL, &extension);
    require(library, "Cannot load bridge in isolated vendor namespace");
    auto* effect = static_cast<sbfx::Library*>(dlsym(library, "AELI"));
    require(effect, "Missing effect API");
    sbfx::Handle handle = nullptr;
    require(effect->create(&sbfx::implementation, 0, 0, &handle) == 0 && handle, "Cannot create effect");
    auto status = [&](uint32_t code, uint32_t size, void* data) {
        int32_t reply = -1;
        uint32_t reply_size = sizeof(reply);
        const int result = (*handle)->command(handle, code, size, data, &reply_size, &reply);
        if (result || reply)
            std::fprintf(stderr, "Effect command %u failed: transport=%d status=%d\n", code, result, reply);
        require(result == 0 && reply_size == sizeof(reply) && reply == 0, "Namespace effect command rejected");
    };
    status(sbfx::Init, 0, nullptr);
    sbfx::Config config{};
    config.input.rate = config.output.rate = 48000;
    config.input.channels = config.output.channels = 3;
    config.input.format = config.output.format = 5;
    config.input.mask = config.output.mask = sbfx::pcm_config;
    config.input.access = 1;
    config.output.access = 0;
    status(sbfx::SetConfig, sizeof(config), &config);
    uint32_t device = sbfx::speaker;
    require((*handle)->command(handle, sbfx::SetDevice, sizeof(device), &device, nullptr, nullptr) == 0,
            "Cannot set speaker route");
    status(sbfx::Enable, 0, nullptr);
    float input[512], output[512]{};
    for (size_t i = 0; i < 512; ++i) input[i] = (i / 32 % 2 ? 0.01f : -0.01f);
    sbfx::Buffer in{256, input}, out{256, output};
    bool changed = false;
    for (int i = 0; i < 4; ++i) {
        require((*handle)->process(handle, &in, &out) == 0, "Namespace processing failed");
        changed |= std::memcmp(input, output, sizeof(input)) != 0;
    }
    require(changed, "Engine did not alter synthetic input");
    int descriptors[2];
    require(pipe(descriptors) == 0, "Cannot create diagnostics pipe");
    int32_t fd = descriptors[1];
    require((*handle)->command(handle, sbfx::Dump, sizeof(fd), &fd, nullptr, nullptr) == 0, "Dump failed");
    close(descriptors[1]);
    char dump[512]{};
    const ssize_t count = read(descriptors[0], dump, sizeof(dump) - 1);
    close(descriptors[0]);
    require(count > 0 && std::strstr(dump, "configured=1 enabled=1 device=0x2") &&
            std::strstr(dump, "processed_frames=1024 bypassed_frames=0"), "Unexpected processing counters");
    require(effect->release(handle) == 0, "Cannot release namespace effect");
    require(dlclose(library) == 0, "Cannot close namespace bridge");
    std::puts("{\"isolated_vendor_namespace\":true,\"runtime_preloaded\":false,"
              "\"processed_frames\":1024,\"bypassed_frames\":0,\"hidl_mask\":30}");
}
