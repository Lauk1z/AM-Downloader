// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include <windows.h>
#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

inline uint8_t reverse_bits(uint8_t x) {
    x = (x >> 4) | (x << 4);
    x = ((x & 0xcc) >> 2) | ((x & 0x33) << 2);
    return ((x & 0xaa) >> 1) | ((x & 0x55) << 1);
}
inline uint64_t number(const uint8_t* p, int n, bool little) {
    uint64_t v = 0;
    for (int i = 0; i < n; ++i) v = (v << 8) | p[little ? n - i - 1 : i];
    return v;
}

// Canonical DSD is byte-interleaved, oldest bit in the MSB. No PCM conversion.
class DsdFile {
    std::ifstream file;
    uint64_t start = 0, cursor = 0, cached = UINT64_MAX;
    uint32_t block = 0;
    bool lsbf = false;
    std::vector<uint8_t> cache;
    std::vector<uint8_t> at(uint64_t pos, size_t n) {
        std::vector<uint8_t> data(n);
        file.seekg(pos); file.read(reinterpret_cast<char*>(data.data()), n);
        if (size_t(file.gcount()) != n) throw std::runtime_error("Truncated DSD file");
        return data;
    }
public:
    uint32_t rate = 0, channels = 0;
    uint64_t frames = 0; // one byte (8 DSD samples) per channel
    explicit DsdFile(const std::wstring& path, uint64_t position = 0) : file(std::filesystem::path(path), std::ios::binary) {
        if (!file) throw std::runtime_error("Cannot open DSD file");
        uint64_t size = std::filesystem::file_size(path);
        auto h = at(0, 28);
        if (!memcmp(h.data(), "DSD ", 4)) {
            auto fmt = at(28, 52);
            if (memcmp(fmt.data(), "fmt ", 4) || number(fmt.data()+4,8,true)!=52 || number(fmt.data()+16,4,true)!=0)
                throw std::runtime_error("Unsupported DSF header");
            channels = uint32_t(number(fmt.data()+24,4,true)); rate = uint32_t(number(fmt.data()+28,4,true));
            auto bits = number(fmt.data()+32,4,true);
            if (bits != 1 && bits != 8) throw std::runtime_error("Invalid DSF bit order");
            lsbf = bits == 1; frames = number(fmt.data()+36,8,true)/8; block = uint32_t(number(fmt.data()+44,4,true));
            auto data = at(80,12);
            if (memcmp(data.data(), "data", 4) || !block || block > 1048576) throw std::runtime_error("Invalid DSF data");
            start = 92;
            if (!channels || channels > 32 || frames > (size-start)/channels || ((frames+block-1)/block)*block*channels > size-start)
                throw std::runtime_error("Truncated DSF samples");
            cache.resize(size_t(block)*channels);
        } else if (!memcmp(h.data(), "FRM8", 4) && !memcmp(h.data()+12, "DSD ", 4)) {
            bool raw = false;
            for (uint64_t p = 16; p+12 <= size;) {
                auto chunk = at(p,12); uint64_t n = number(chunk.data()+4,8,false);
                if (n > size-p-12) throw std::runtime_error("Invalid DFF chunk size");
                if (!memcmp(chunk.data(), "PROP",4)) {
                    if (n < 4) throw std::runtime_error("Invalid DFF properties");
                    for (uint64_t q = p+16; q+12 <= p+12+n;) {
                        auto tag = at(q,12); uint64_t len = number(tag.data()+4,8,false);
                        if (len > p+12+n-q-12) throw std::runtime_error("Invalid DFF property");
                        if (!memcmp(tag.data(),"FS  ",4) && len>=4) rate = uint32_t(number(at(q+12,4).data(),4,false));
                        if (!memcmp(tag.data(),"CHNL",4) && len>=2) channels = uint32_t(number(at(q+12,2).data(),2,false));
                        if (!memcmp(tag.data(),"CMPR",4) && len>=4) raw = !memcmp(at(q+12,4).data(),"DSD ",4);
                        q += 12+len+(len&1);
                    }
                }
                if (!memcmp(chunk.data(),"DSD ",4)) { start = p+12; frames = n; }
                p += 12+n+(n&1);
            }
            if (!raw || !start || !channels) throw std::runtime_error("Native DSD requires uncompressed DFF (DST is not supported)");
            frames /= channels;
        } else throw std::runtime_error("Native DSD/DoP supports DSF and uncompressed DFF/DSDIFF");
        if (!rate || !channels || channels > 32 || !frames) throw std::runtime_error("Invalid DSD format");
        cursor = std::min(frames, position * rate / 8000);
    }
    size_t read(uint8_t* out, size_t count) {
        count = size_t(std::min<uint64_t>(count, frames-cursor));
        if (!block) {
            file.seekg(start+cursor*channels); file.read(reinterpret_cast<char*>(out), count*channels);
            if (size_t(file.gcount()) != count*channels) throw std::runtime_error("DSD read failed");
        } else {
            for (size_t i=0; i<count; ++i) {
                uint64_t group = (cursor+i)/block;
                if (cached != group) {
                    file.seekg(start+group*block*channels); file.read(reinterpret_cast<char*>(cache.data()),cache.size());
                    if (size_t(file.gcount()) != cache.size()) throw std::runtime_error("DSF read failed");
                    cached = group;
                }
                for (uint32_t c=0; c<channels; ++c) {
                    auto b = cache[c*block+(cursor+i)%block]; out[i*channels+c] = lsbf ? reverse_bits(b) : b;
                }
            }
        }
        cursor += count; return count;
    }
};

inline std::wstring quoted(const std::wstring& s) {
    std::wstring out = L"\""; size_t slashes = 0;
    for (wchar_t c : s) {
        if (c == L'\\') { ++slashes; continue; }
        out.append(slashes*(c==L'"'?2:1),L'\\'); slashes=0;
        if (c == L'"') out += L'\\'; out += c;
    }
    out.append(slashes*2,L'\\'); return out+L'"';
}

// FFmpeg handles the existing PCM formats in a separate process. Its pipe is
// read only by the producer thread, never by an ASIO / WASAPI audio callback.
class PcmPipe {
    HANDLE pipe = nullptr, process = nullptr, job = nullptr;
public:
    PcmPipe(const std::wstring& ffmpeg, const std::wstring& path, uint64_t position, uint32_t rate=0, uint32_t channels=0) {
        SECURITY_ATTRIBUTES sa{sizeof(sa),nullptr,TRUE}; HANDLE writer = nullptr;
        if (!CreatePipe(&pipe,&writer,&sa,0)) throw std::runtime_error("Cannot create decoder pipe");
        SetHandleInformation(pipe,HANDLE_FLAG_INHERIT,0);
        HANDLE null = CreateFileW(L"NUL",GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,&sa,OPEN_EXISTING,0,nullptr);
        STARTUPINFOW si{sizeof(si)}; si.dwFlags=STARTF_USESTDHANDLES; si.hStdInput=null; si.hStdError=null; si.hStdOutput=writer;
        PROCESS_INFORMATION pi{};
        auto command = quoted(ffmpeg)+L" -nostdin -v error -ss "+std::to_wstring(position/1000.0)+L" -i "+quoted(path)+L" -map 0:a:0 -vn -sn -dn";
        if(rate) command+=L" -ar "+std::to_wstring(rate);
        if(channels) command+=L" -ac "+std::to_wstring(channels);
        command+=L" -c:a pcm_s32le -f s32le pipe:1";
        bool ok = CreateProcessW(ffmpeg.c_str(),command.data(),nullptr,nullptr,TRUE,CREATE_NO_WINDOW|CREATE_SUSPENDED,nullptr,nullptr,&si,&pi);
        CloseHandle(writer); CloseHandle(null);
        if (!ok) { CloseHandle(pipe); pipe=nullptr; throw std::runtime_error("Cannot start bundled FFmpeg"); }
        process=pi.hProcess;
        job=CreateJobObjectW(nullptr,nullptr); JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!job || !SetInformationJobObject(job,JobObjectExtendedLimitInformation,&limits,sizeof(limits)) || !AssignProcessToJobObject(job,process)) {
            TerminateProcess(process,1); CloseHandle(pi.hThread); CloseHandle(process); CloseHandle(pipe); if(job) CloseHandle(job);
            throw std::runtime_error("Cannot supervise audio decoder");
        }
        ResumeThread(pi.hThread); CloseHandle(pi.hThread);
    }
    size_t read(uint8_t* out, size_t bytes) {
        DWORD got=0;
        if (!ReadFile(pipe,out,DWORD(bytes),&got,nullptr) && GetLastError()!=ERROR_BROKEN_PIPE) throw std::runtime_error("PCM decoder read failed");
        if (!got) {
            WaitForSingleObject(process,5000); DWORD code=0; GetExitCodeProcess(process,&code);
            if (code) throw std::runtime_error("FFmpeg could not decode this audio file");
        }
        return got;
    }
    void cancel() { if (process) TerminateProcess(process,0); }
    ~PcmPipe() { cancel(); if(pipe) CloseHandle(pipe); if(process) CloseHandle(process); if(job) CloseHandle(job); }
};
