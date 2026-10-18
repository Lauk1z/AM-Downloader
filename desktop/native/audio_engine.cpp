// SPDX-License-Identifier: AGPL-3.0-or-later
// Isolated Windows output host. stdin: pause/resume/stop; stdout: JSON events.
#define NOMINMAX
#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <functiondiscoverykeys_devpkey.h>
#include <avrt.h>
#include <wrl/client.h>
#include <atomic>
#include <chrono>
#include <iostream>
#include <map>
#include <thread>
#include "asio/iasiodrv.h"
#include "audio_source.h"
using Microsoft::WRL::ComPtr;

static std::string utf8(const std::wstring& s) {
    int n=WideCharToMultiByte(CP_UTF8,0,s.data(),int(s.size()),nullptr,0,nullptr,nullptr);
    std::string r(n,'\0'); WideCharToMultiByte(CP_UTF8,0,s.data(),int(s.size()),r.data(),n,nullptr,nullptr); return r;
}
static std::string json(const std::string& s) {
    std::string out="\"";
    for (unsigned char c:s) { if(c=='"'||c=='\\') out+='\\'; if(c<32) out+=' '; else out+=c; }
    return out+'"';
}
static void check(HRESULT hr, const char* operation) {
    if (FAILED(hr)) throw std::runtime_error(std::string(operation)+" (Windows error "+std::to_string(uint32_t(hr))+")");
}
static void asio_check(ASIOError e, const char* operation) {
    if(e!=ASE_OK && e!=ASE_SUCCESS) throw std::runtime_error(std::string(operation)+" (ASIO error "+std::to_string(e)+")");
}
struct Device { std::wstring id, name; };
static std::vector<Device> asio_devices() {
    std::vector<Device> out; HKEY key;
    if(RegOpenKeyExW(HKEY_LOCAL_MACHINE,L"SOFTWARE\\ASIO",0,KEY_READ|KEY_WOW64_64KEY,&key)!=ERROR_SUCCESS) return out;
    for (DWORD i=0;;++i) {
        wchar_t name[512]; DWORD n=512;
        if(RegEnumKeyExW(key,i,name,&n,nullptr,nullptr,nullptr,nullptr)!=ERROR_SUCCESS) break;
        wchar_t clsid[128]; DWORD size=sizeof(clsid);
        if(RegGetValueW(key,name,L"CLSID",RRF_RT_REG_SZ,nullptr,clsid,&size)==ERROR_SUCCESS) out.push_back({clsid,name});
    }
    RegCloseKey(key); return out;
}
static ComPtr<IMMDeviceEnumerator> enumerator() {
    ComPtr<IMMDeviceEnumerator> e; check(CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_ALL,IID_PPV_ARGS(&e)),"Audio devices"); return e;
}
static std::string device_name(IMMDevice* device) {
    ComPtr<IPropertyStore> props; check(device->OpenPropertyStore(STGM_READ,&props),"Device properties");
    PROPVARIANT v; PropVariantInit(&v); check(props->GetValue(PKEY_Device_FriendlyName,&v),"Device name");
    std::string name=v.vt==VT_LPWSTR ? utf8(v.pwszVal):"Audio device"; PropVariantClear(&v); return name;
}
static void list_devices() {
    auto e=enumerator(); ComPtr<IMMDeviceCollection> all; check(e->EnumAudioEndpoints(eRender,DEVICE_STATE_ACTIVE,&all),"Enumerate outputs");
    UINT count=0; all->GetCount(&count);
    for(UINT i=0;i<count;++i) {
        ComPtr<IMMDevice> d; all->Item(i,&d); LPWSTR id=nullptr; d->GetId(&id);
        std::cout<<"{\"kind\":\"wasapi\",\"id\":"<<json(utf8(id))<<",\"name\":"<<json(device_name(d.Get()))<<"}\n"; CoTaskMemFree(id);
    }
    for(auto& d:asio_devices()) std::cout<<"{\"kind\":\"asio\",\"id\":"<<json(utf8(d.id))<<",\"name\":"<<json(utf8(d.name))<<"}\n";
    std::cout.flush();
}

// SPSC byte ring. Allocation, decoding, IO and locks never occur in the callback.
struct Ring {
    std::vector<uint8_t> bytes;
    std::atomic<uint64_t> read{0}, written{0};
    explicit Ring(size_t size):bytes(size){}
    size_t available() const { return size_t(written.load(std::memory_order_acquire)-read.load(std::memory_order_acquire)); }
    size_t push(const uint8_t* src,size_t n) {
        uint64_t w=written.load(); n=std::min(n,bytes.size()-size_t(w-read.load(std::memory_order_acquire)));
        size_t pos=w%bytes.size(), first=std::min(n,bytes.size()-pos);
        memcpy(bytes.data()+pos,src,first); memcpy(bytes.data(),src+first,n-first); written.store(w+n,std::memory_order_release); return n;
    }
    size_t pop(uint8_t* dst,size_t n,size_t alignment) {
        uint64_t r=read.load(); n=std::min(n,size_t(written.load(std::memory_order_acquire)-r)); n-=n%alignment;
        size_t pos=r%bytes.size(),first=std::min(n,bytes.size()-pos);
        memcpy(dst,bytes.data()+pos,first); memcpy(dst+first,bytes.data(),n-first); read.store(r+n,std::memory_order_release); return n;
    }
};
struct Stream {
    uint32_t rate, channels; std::string format;
    Ring ring;
    std::atomic<bool> quit{false}, eof{false}, failed{false}, underrun{false};
    std::string error;
    std::atomic<uint64_t> consumed{0};
    std::thread producer;
    std::unique_ptr<DsdFile> dsd; std::unique_ptr<PcmPipe> pcm;
    uint64_t markerFrame=0;
    std::vector<uint8_t> scratch;
    Stream(uint32_t r,uint32_t ch,std::string f):rate(r),channels(ch),format(f),ring(std::min<size_t>(64*1024*1024,std::max<size_t>(1024*1024,size_t(r)*ch/2))) {}
    size_t unit() const { return channels*(format=="pcm"?4:format=="dop"?2:1); }
    uint32_t frame_rate() const { return format=="dsd"?rate/8:format=="dop"?rate/16:rate; }
    void start(const std::wstring& file,const std::wstring& decoder,uint64_t position,bool shared=false) {
        if(format=="pcm") pcm=std::make_unique<PcmPipe>(decoder,file,position,shared?rate:0,shared?channels:0);
        else {
            dsd=std::make_unique<DsdFile>(file,position);
            if(dsd->rate!=rate || dsd->channels!=channels) throw std::runtime_error("DSD source format mismatch");
        }
        producer=std::thread([this] {
            try {
                std::vector<uint8_t> data(65536*channels);
                while(!quit) {
                    size_t n=dsd ? dsd->read(data.data(),65536)*channels : pcm->read(data.data(),data.size());
                    if(!n) break;
                    for(size_t p=0;p<n && !quit;) { auto got=ring.push(data.data()+p,n-p); p+=got; if(!got) Sleep(1); }
                }
            } catch(const std::exception& e) { error=e.what(); failed.store(true,std::memory_order_release); }
            eof.store(true,std::memory_order_release);
        });
    }
    void prepare(size_t frames) { scratch.resize(frames*unit()); }
    size_t pull(size_t frames) {
        size_t bytes=frames*unit(), got=ring.pop(scratch.data(),bytes,unit());
        memset(scratch.data()+got,format=="pcm"?0:0x69,bytes-got);
        consumed.fetch_add(got/unit());
        if(got<bytes && !eof) underrun=true;
        return got/unit();
    }
    uint32_t sample(size_t frame,size_t ch) const {
        if(format=="dop") {
            // DoP: oldest DSD bit is bit 15, marker occupies bits 23..16.
            size_t p=frame*channels*2+ch;
            return (uint32_t((markerFrame+frame)&1?0xfa:0x05)<<24) | (uint32_t(scratch[p])<<16) | (uint32_t(scratch[p+channels])<<8);
        }
        uint32_t v; memcpy(&v,scratch.data()+(frame*channels+ch)*4,4); return v;
    }
    ~Stream() { quit=true; if(pcm) pcm->cancel(); if(producer.joinable()) producer.join(); }
};

static WAVEFORMATEXTENSIBLE wave_format(uint32_t rate,uint32_t ch,int bits,int valid) {
    WAVEFORMATEXTENSIBLE w{}; w.Format.wFormatTag=WAVE_FORMAT_EXTENSIBLE; w.Format.nChannels=WORD(ch);
    w.Format.nSamplesPerSec=rate; w.Format.wBitsPerSample=WORD(bits); w.Format.nBlockAlign=WORD(ch*bits/8);
    w.Format.nAvgBytesPerSec=rate*w.Format.nBlockAlign; w.Format.cbSize=22; w.Samples.wValidBitsPerSample=WORD(valid);
    w.dwChannelMask=ch==1?SPEAKER_FRONT_CENTER:ch==2?SPEAKER_FRONT_LEFT|SPEAKER_FRONT_RIGHT:0;
    w.SubFormat=KSDATAFORMAT_SUBTYPE_PCM; return w;
}
struct Wasapi {
    ComPtr<IMMDevice> device; ComPtr<IAudioClient> client; ComPtr<IAudioRenderClient> render;
    HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr); UINT32 frames=0;
    WAVEFORMATEXTENSIBLE wave{}; std::string name; bool shared=false;
    ComPtr<ISimpleAudioVolume> volume;
    void init(const std::wstring& id,Stream& stream,int sourceBits,bool useShared=false) {
        shared=useShared;
        auto e=enumerator(); HRESULT opened=E_FAIL;
        // Some USB drivers rebuild their WASAPI endpoint after leaving ASIO DSD.
        for(int attempt=0;attempt<15;++attempt) {
            check(id.empty() && shared ? e->GetDefaultAudioEndpoint(eRender,eMultimedia,&device) : e->GetDevice(id.c_str(),&device),"Selected output is unavailable");
            opened=device->Activate(__uuidof(IAudioClient),CLSCTX_ALL,nullptr,&client);
            if(opened!=AUDCLNT_E_DEVICE_INVALIDATED) break;
            Sleep(100);
        }
        check(opened,"Open output"); name=device_name(device.Get());
        if(shared) {
            wave=wave_format(stream.frame_rate(),stream.channels,32,32);
            check(client->Initialize(AUDCLNT_SHAREMODE_SHARED,AUDCLNT_STREAMFLAGS_EVENTCALLBACK|AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM|AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,0,0,&wave.Format,nullptr),"WASAPI shared initialization");
            check(client->SetEventHandle(event),"Shared output event");
            check(client->GetBufferSize(&frames),"Shared output buffer");
            check(client->GetService(IID_PPV_ARGS(&render)),"Shared output service");
            check(client->GetService(IID_PPV_ARGS(&volume)),"Shared session volume");
            stream.prepare(frames); return;
        }
        bool found=false;
        for(auto [bits,valid]:std::vector<std::pair<int,int>>{{32,32},{32,24},{24,24},{16,16}}) {
            if(valid < (stream.format=="dop"?24:sourceBits)) continue;
            auto test=wave_format(stream.frame_rate(),stream.channels,bits,valid);
            if(client->IsFormatSupported(AUDCLNT_SHAREMODE_EXCLUSIVE,&test.Format,nullptr)==S_OK) {wave=test;found=true;break;}
        }
        if(!found) throw std::runtime_error("Device does not support this rate/bit depth in exclusive mode; no resampling or PCM fallback was performed");
        REFERENCE_TIME period=0; check(client->GetDevicePeriod(nullptr,&period),"Device period");
        period=std::max<REFERENCE_TIME>(period,100000); // 10 ms or driver minimum
        auto hr=client->Initialize(AUDCLNT_SHAREMODE_EXCLUSIVE,AUDCLNT_STREAMFLAGS_EVENTCALLBACK,period,period,&wave.Format,nullptr);
        if(hr==AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED) {
            check(client->GetBufferSize(&frames),"Aligned buffer"); period=REFERENCE_TIME(10000000.0*frames/wave.Format.nSamplesPerSec+.5);
            client.Reset(); check(device->Activate(__uuidof(IAudioClient),CLSCTX_ALL,nullptr,&client),"Reopen aligned output");
            hr=client->Initialize(AUDCLNT_SHAREMODE_EXCLUSIVE,AUDCLNT_STREAMFLAGS_EVENTCALLBACK,period,period,&wave.Format,nullptr);
        }
        check(hr,"WASAPI exclusive initialization (device may be busy)"); check(client->SetEventHandle(event),"Output event");
        check(client->GetBufferSize(&frames),"Output buffer"); check(client->GetService(IID_PPV_ARGS(&render)),"Output service"); stream.prepare(frames);
    }
    void fill(Stream& stream) {
        UINT32 count=frames;
        if(shared) { UINT32 padding=0; check(client->GetCurrentPadding(&padding),"Shared output padding"); count=frames-padding; }
        if(!count) return;
        BYTE* data; check(render->GetBuffer(count,&data),"Output buffer lost"); stream.pull(count);
        int bytes=wave.Format.wBitsPerSample/8;
        for(UINT32 f=0;f<count;++f) for(uint32_t c=0;c<stream.channels;++c) {
            uint32_t value=stream.sample(f,c)>>(32-wave.Format.wBitsPerSample);
            memcpy(data+(f*stream.channels+c)*bytes,&value,bytes);
        }
        stream.markerFrame+=count; check(render->ReleaseBuffer(count,0),"Send output");
    }
    ~Wasapi() { if(client) client->Stop(); CloseHandle(event); }
};

struct Asio {
    IASIO* driver=nullptr; Stream* stream=nullptr; bool initialized=false, buffers=false, running=false;
    std::vector<ASIOBufferInfo> info; std::vector<ASIOChannelInfo> channels;
    long frames=0; int outputBits=32; std::string name; std::atomic<bool> reset{false};
    static Asio* active;
    static void callback(long index,ASIOBool) { if(active) active->fill(index); }
    static ASIOTime* time_callback(ASIOTime*,long index,ASIOBool now) {callback(index,now);return nullptr;}
    static void rate_changed(ASIOSampleRate) { if(active) active->reset=true; }
    static long message(long selector,long value,void*,double*) {
        if(selector==kAsioSelectorSupported) return value==kAsioResetRequest || value==kAsioEngineVersion || value==kAsioResyncRequest;
        if(selector==kAsioEngineVersion) return 2;
        if(selector==kAsioResetRequest || selector==kAsioResyncRequest) {if(active) active->reset=true;return 1;}
        return 0;
    }
    ASIOCallbacks callbacks{callback,rate_changed,message,time_callback};
    void open(const std::wstring& id) {
        CLSID cls; check(CLSIDFromString(id.c_str(),&cls),"ASIO driver ID");
        check(CoCreateInstance(cls,nullptr,CLSCTX_INPROC_SERVER,cls,reinterpret_cast<void**>(&driver)),"Load ASIO driver");
        name=utf8(id); for(auto& device:asio_devices()) if(device.id==id) {name=utf8(device.name);break;}
        if(!driver->init(GetDesktopWindow())) {
            char error[256]{}; driver->getErrorMessage(error);
            throw std::runtime_error("ASIO 驱动初始化失败："+name+(error[0]?" · "+std::string(error):"")+"。请确认选择的是 DAC 对应的驱动，并检查设备连接及其他程序占用。");
        }
        initialized=true;
        char text[256]{}; driver->getDriverName(text); if(text[0]) name=text;
    }
    void mode(bool dsd) {
        ASIOIoFormat format{}; format.FormatType=dsd?kASIODSDFormat:kASIOPCMFormat;
        auto result=driver->future(kAsioSetIoFormat,&format);
        if(dsd) asio_check(result,"Driver does not support native DSD");
    }
    void init(const std::wstring& id,Stream& s,int sourceBits) {
        stream=&s; open(id); mode(s.format=="dsd");
        double rate=s.format=="dsd"?s.rate:s.frame_rate();
        asio_check(driver->canSampleRate(rate),"ASIO does not support requested sample rate"); asio_check(driver->setSampleRate(rate),"Set ASIO sample rate");
        double actual=0; asio_check(driver->getSampleRate(&actual),"Read ASIO sample rate");
        if(actual!=rate) throw std::runtime_error("ASIO rate differs from source; direct output stopped");
        long inputs=0,outputs=0,minimum=0,maximum=0,preferred=0,granularity=0;
        asio_check(driver->getChannels(&inputs,&outputs),"ASIO channels");
        if(outputs<long(s.channels)) throw std::runtime_error("ASIO device has too few channels");
        asio_check(driver->getBufferSize(&minimum,&maximum,&preferred,&granularity),"ASIO buffer size");
        if(preferred<=0 || preferred>16*1024*1024) throw std::runtime_error("Invalid ASIO buffer size");
        frames=preferred;
        if(s.format=="dsd") { if(frames%8) throw std::runtime_error("DSD buffer is not byte aligned"); frames/=8; outputBits=1; }
        s.prepare(frames); info.resize(s.channels); channels.resize(s.channels);
        for(uint32_t c=0;c<s.channels;++c) {
            info[c].isInput=ASIOFalse; info[c].channelNum=c;
            channels[c].channel=c; channels[c].isInput=ASIOFalse; asio_check(driver->getChannelInfo(&channels[c]),"ASIO channel format");
            auto type=channels[c].type;
            if(s.format=="dsd") {
                if(type!=ASIOSTDSDInt8MSB1 && type!=ASIOSTDSDInt8LSB1) throw std::runtime_error("ASIO driver did not expose packed 1-bit DSD channels");
            } else {
                int bits=type==ASIOSTInt16LSB?16:type==ASIOSTInt24LSB||type==ASIOSTInt32LSB24?24:type==ASIOSTInt32LSB?32:0;
                if(bits<(s.format=="dop"?24:sourceBits)) throw std::runtime_error("ASIO integer sample format cannot preserve source precision");
                outputBits=std::min(outputBits,bits);
            }
        }
        active=this; reset=false;
        asio_check(driver->createBuffers(info.data(),long(info.size()),preferred,&callbacks),"Create ASIO buffers"); buffers=true;
    }
    void fill(long index) {
        stream->pull(frames);
        for(size_t c=0;c<channels.size();++c) {
            uint8_t* out=static_cast<uint8_t*>(info[c].buffers[index]); auto type=channels[c].type;
            if(stream->format=="dsd") {
                for(long f=0;f<frames;++f) {auto b=stream->scratch[f*channels.size()+c];out[f]=type==ASIOSTDSDInt8LSB1?reverse_bits(b):b;}
            } else {
                int bytes=type==ASIOSTInt16LSB?2:type==ASIOSTInt24LSB?3:4;
                int shift=type==ASIOSTInt32LSB24?8:32-bytes*8;
                for(long f=0;f<frames;++f) {int32_t v=int32_t(stream->sample(f,c))>>shift;memcpy(out+f*bytes,&v,bytes);}
            }
        }
        stream->markerFrame+=frames; driver->outputReady();
    }
    void play() {asio_check(driver->start(),"Start ASIO output");running=true;}
    void pause() {if(running) asio_check(driver->stop(),"Pause ASIO output");running=false;}
    ~Asio() {
        if(driver) { if(running) driver->stop(); if(buffers) driver->disposeBuffers(); if(initialized) { ASIOIoFormat f{}; f.FormatType=kASIOPCMFormat; driver->future(kAsioSetIoFormat,&f); } driver->Release(); }
        if(active==this) active=nullptr;
    }
};
Asio* Asio::active=nullptr;

static void probe_asio(const std::wstring& id) {
    Asio asio; asio.open(id); asio.mode(true);
    std::cout<<"{\"event\":\"capabilities\",\"name\":"<<json(asio.name)<<",\"dsd_rates\":[";
    bool first=true;
    for(int multiple:{64,128,256,512,1024}) if(asio.driver->canSampleRate(44100.0*multiple)==ASE_OK) {
        if(!first) std::cout<<','; first=false; std::cout<<multiple;
    }
    std::cout<<"]}"<<std::endl;
}

static int run(int argc,wchar_t** argv) {
    std::map<std::wstring,std::wstring> args;
    for(int i=1;i<argc;++i) {std::wstring key=argv[i];args[key]=(i+1<argc && wcsncmp(argv[i+1],L"--",2))?argv[++i]:L"1";}
    if(args.count(L"--list")) {list_devices();return 0;}
    if(args.count(L"--probe-asio")) {probe_asio(args[L"--probe-asio"]);return 0;}
    auto format=utf8(args[L"--format"]); auto mode=utf8(args[L"--mode"]);
    if(format!="pcm" && format!="dop" && format!="dsd") throw std::runtime_error("Invalid output format");
    if(mode!="wasapi" && mode!="asio" && mode!="render" && mode!="shared") throw std::runtime_error("Invalid output mode");
    if(mode=="shared" && format!="pcm") throw std::runtime_error("Shared output requires PCM decoding");
    if(format=="dsd" && mode=="wasapi") throw std::runtime_error("Native DSD requires ASIO");
    uint32_t rate=std::stoul(args[L"--rate"]), channels=std::stoul(args[L"--channels"]);
    if(!rate || rate>50000000 || !channels || channels>32) throw std::runtime_error("Invalid audio format");
    int bits=args.count(L"--bits")?std::stoi(args[L"--bits"]):24;
    uint64_t position=args.count(L"--position")?std::stoull(args[L"--position"]):0;
    Stream stream(rate,channels,format);
    stream.start(args[L"--file"],args[L"--ffmpeg"],position,mode=="shared");
    auto deadline=GetTickCount64()+15000;
    while(stream.ring.available()<std::min<size_t>(stream.ring.bytes.size()/2,stream.frame_rate()*stream.unit()/4) && !stream.eof) {
        if(GetTickCount64()>deadline) throw std::runtime_error("Audio prebuffer timed out"); Sleep(2);
    }
    if(stream.failed) throw std::runtime_error(stream.error);
    if(mode=="render") {
        // Deterministic offline verification uses the same parser and DoP packer.
        std::ofstream out(std::filesystem::path(args[L"--output"]),std::ios::binary); stream.prepare(4096);
        while(!stream.eof || stream.ring.available()>=stream.unit()) {
            auto n=std::min<size_t>(4096,stream.ring.available()/stream.unit()); if(!n) {Sleep(1);continue;}
            stream.pull(n);
            if(format=="dsd") out.write(reinterpret_cast<char*>(stream.scratch.data()),n*channels);
            else for(size_t f=0;f<n;++f) for(uint32_t c=0;c<channels;++c) {auto v=stream.sample(f,c);out.write(reinterpret_cast<char*>(&v),4);}
            stream.markerFrame+=n;
        }
        if(stream.failed) throw std::runtime_error(stream.error);
        if(!out) throw std::runtime_error("Cannot write verification output");
        return 0;
    }
    Wasapi wasapi; Asio asio; std::string name; uint32_t bufferFrames; int outputBits=1;
    bool windowsOutput=mode=="wasapi" || mode=="shared";
    if(windowsOutput) {wasapi.init(args[L"--device"],stream,bits,mode=="shared");name=wasapi.name;bufferFrames=wasapi.frames;outputBits=wasapi.wave.Samples.wValidBitsPerSample;}
    else {asio.init(args[L"--device"],stream,bits);name=asio.name;bufferFrames=uint32_t(asio.frames);outputBits=asio.outputBits;}
    DWORD task=0; HANDLE priority=AvSetMmThreadCharacteristicsW(L"Pro Audio",&task);
    if(mode=="shared") check(wasapi.volume->SetMasterVolume(args.count(L"--volume")?std::stof(args[L"--volume"]):.65f,nullptr),"Shared volume");
    if(windowsOutput) {wasapi.fill(stream);check(wasapi.client->Start(),"Start Windows output");} else asio.play();
    std::cout<<"{\"event\":\"ready\",\"mode\":"<<json(mode)<<",\"format\":"<<json(format)<<",\"device\":"<<json(name)<<",\"rate\":"<<(format=="dsd"?rate:stream.frame_rate())<<",\"bits\":"<<outputBits<<",\"buffer_frames\":"<<bufferFrames<<"}"<<std::endl;
    bool paused=false,finished=false; std::string commands; auto last=GetTickCount64(), drained=uint64_t(0), lastBuffer=last, lastConsumed=uint64_t(0);
    while(!finished) {
        MSG msg; while(PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)) {TranslateMessage(&msg);DispatchMessageW(&msg);}
        DWORD available=0;
        if(!PeekNamedPipe(GetStdHandle(STD_INPUT_HANDLE),nullptr,0,nullptr,&available,nullptr)) break;
        if(available) {
            char buf[256];DWORD n; if(ReadFile(GetStdHandle(STD_INPUT_HANDLE),buf,std::min<DWORD>(256,available),&n,nullptr)) commands.append(buf,n);
            size_t nl;
            while((nl=commands.find('\n'))!=std::string::npos) {
                auto cmd=commands.substr(0,nl);commands.erase(0,nl+1);
                if(!cmd.empty() && cmd.back()=='\r') cmd.pop_back();
                if(cmd=="stop") finished=true;
                else if(mode=="shared" && cmd.rfind("volume ",0)==0) check(wasapi.volume->SetMasterVolume(std::clamp(std::stof(cmd.substr(7)),0.f,1.f),nullptr),"Shared volume");
                else if(cmd=="pause" && !paused) {
                    if(windowsOutput) check(wasapi.client->Stop(),"Pause output"); else asio.pause(); paused=true;
                    std::cout<<"{\"event\":\"paused\"}"<<std::endl;
                } else if(cmd=="resume" && paused) {
                    if(windowsOutput) check(wasapi.client->Start(),"Resume output"); else asio.play();paused=false;lastBuffer=GetTickCount64();
                    std::cout<<"{\"event\":\"playing\"}"<<std::endl;
                }
            }
        }
        if(finished) break;
        if(stream.failed) throw std::runtime_error(stream.error);
        if(stream.underrun) throw std::runtime_error("Audio buffer underrun; output stopped to preserve the DSD/PCM stream");
        if(asio.reset) throw std::runtime_error("ASIO driver requested a reset; select the device and play again");
        if(!paused && windowsOutput) {
            if(WaitForSingleObject(wasapi.event,5)==WAIT_OBJECT_0) {wasapi.fill(stream);lastBuffer=GetTickCount64();}
            else if(GetTickCount64()-lastBuffer>3000) throw std::runtime_error("Output device stopped responding or was disconnected");
        } else Sleep(5);
        auto now=GetTickCount64();
        if(mode=="asio") {
            auto consumed=stream.consumed.load();
            if(paused || consumed!=lastConsumed) {lastBuffer=now;lastConsumed=consumed;}
            else if(stream.ring.available()>=stream.unit() && now-lastBuffer>3000) throw std::runtime_error("ASIO device stopped responding or was disconnected");
        }
        if(now-last>=40) {
            std::cout<<"{\"event\":\"position\",\"ms\":"<<position+stream.consumed.load()*1000/stream.frame_rate()<<"}"<<std::endl;last=now;
        }
        if(!paused && stream.eof && stream.ring.available()<stream.unit()) {
            if(!drained) drained=now;
            if(now-drained>100+bufferFrames*2000/stream.frame_rate()) {std::cout<<"{\"event\":\"end\"}"<<std::endl;finished=true;}
        } else drained=0;
    }
    if(priority) AvRevertMmThreadCharacteristics(priority);
    return 0;
}
int wmain(int argc,wchar_t** argv) {
    SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);
    HRESULT hr=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
    int result=0;
    try {check(hr,"Initialize audio COM");result=run(argc,argv);}
    catch(const std::exception& e) {std::cout<<"{\"event\":\"error\",\"message\":"<<json(e.what())<<"}"<<std::endl;result=1;}
    if(SUCCEEDED(hr)) CoUninitialize();return result;
}
