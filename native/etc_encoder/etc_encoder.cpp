// ETC1 / ETC2 RGB / ETC2 RGBA8 encoder for UnityPy, built as etc_encoder.dll.
// A thin C wrapper over Ericsson's etcpack 2.74 (etcpack/, taken unchanged from
// AMD Compressonator, whose ETC2 encoder it is). The per-block calls mirror
// etcpack's own compressImageFile(); the output is the raw block data Unity
// stores (big-endian words, EAC alpha block first for RGBA8), no container.
// Build: python build_etc_encoder.py

#include <atomic>
#include <mutex>
#include <thread>
#include <vector>
#include <stdlib.h>
#include <string.h>

typedef unsigned char uint8;

// etcpack.cxx
extern int format;
bool readCompressParams(void);
void setupAlphaTableAndValtab();
double compressBlockDiffFlipFast(uint8 *img, uint8 *imgdec, int width, int height, int startx, int starty, unsigned int &c1, unsigned int &c2);
void compressBlockDiffFlipFastPerceptual(uint8 *img, uint8 *imgdec, int width, int height, int startx, int starty, unsigned int &c1, unsigned int &c2);
void compressBlockETC1Exhaustive(uint8 *img, uint8 *imgdec, int width, int height, int startx, int starty, unsigned int &c1, unsigned int &c2);
void compressBlockETC1ExhaustivePerceptual(uint8 *img, uint8 *imgdec, int width, int height, int startx, int starty, unsigned int &c1, unsigned int &c2);
void compressBlockETC2Fast(uint8 *img, uint8 *alphaimg, uint8 *imgdec, int width, int height, int startx, int starty, unsigned int &c1, unsigned int &c2);
void compressBlockETC2FastPerceptual(uint8 *img, uint8 *imgdec, int width, int height, int startx, int starty, unsigned int &c1, unsigned int &c2);
void compressBlockETC2Exhaustive(uint8 *img, uint8 *imgdec, int width, int height, int startx, int starty, unsigned int &c1, unsigned int &c2);
void compressBlockETC2ExhaustivePerceptual(uint8 *img, uint8 *imgdec, int width, int height, int startx, int starty, unsigned int &c1, unsigned int &c2);
void compressBlockAlphaFast(uint8 *data, int ix, int iy, int width, int height, uint8 *returnData);
void compressBlockAlphaSlow(uint8 *data, int ix, int iy, int width, int height, uint8 *returnData);

enum { ETC_ETC1 = 0, ETC_ETC2_RGB = 1, ETC_ETC2_RGBA8 = 2 };
enum { ETC2PACKAGE_RGB_NO_MIPMAPS = 1, ETC2PACKAGE_RGBA_NO_MIPMAPS = 3 };  // etcpack.h

static std::once_flag g_init;

static void put_be(uint8 *out, unsigned int w)
{
    out[0] = (uint8)(w >> 24);
    out[1] = (uint8)(w >> 16);
    out[2] = (uint8)(w >> 8);
    out[3] = (uint8)w;
}

// rgba: width * height * 4 bytes, rows top to bottom; width and height multiples of 4.
// slow: exhaustive search instead of etcpack's fast mode. perceptual: etcpack's
// perceptual error metric instead of plain RGB error. threads: 0 = one per CPU.
// Returns the number of bytes written to out, or -1 on bad arguments / no memory.
extern "C" __declspec(dllexport) int etc_encode(const uint8 *rgba, int width, int height, int kind, int slow,
                                                int perceptual, int threads, uint8 *out, int out_size)
{
    if (!rgba || !out || width <= 0 || height <= 0 || width % 4 || height % 4)
        return -1;
    if (kind != ETC_ETC1 && kind != ETC_ETC2_RGB && kind != ETC_ETC2_RGBA8)
        return -1;
    const int blocks = (width / 4) * (height / 4);
    const int block_size = kind == ETC_ETC2_RGBA8 ? 16 : 8;
    if (out_size < blocks * block_size)
        return -1;

    std::call_once(g_init, [] {
        readCompressParams();
        setupAlphaTableAndValtab();
        // Read by compressBlockETC2Fast only (punch-through alpha when RGBA1); never changed here.
        format = ETC2PACKAGE_RGB_NO_MIPMAPS;
    });

    const size_t pixels = (size_t)width * height;
    uint8 *img = (uint8 *)malloc(pixels * 3);
    uint8 *imgdec = (uint8 *)malloc(pixels * 3);
    uint8 *alpha = (uint8 *)malloc(pixels);
    if (!img || !imgdec || !alpha)
    {
        free(img);
        free(imgdec);
        free(alpha);
        return -1;
    }
    for (size_t i = 0; i < pixels; i++)
    {
        img[3 * i + 0] = rgba[4 * i + 0];
        img[3 * i + 1] = rgba[4 * i + 1];
        img[3 * i + 2] = rgba[4 * i + 2];
        alpha[i] = rgba[4 * i + 3];
    }

    // etcpack only writes its globals in the setup above, so block rows can be encoded
    // in parallel; each row writes its own part of imgdec and of out.
    const int rows = height / 4;
    const size_t row_bytes = (size_t)(width / 4) * block_size;
    std::atomic<int> next_row(0);
    auto work = [&] {
        for (int row; (row = next_row++) < rows;)
        {
            const int y = row * 4;
            uint8 *p = out + row * row_bytes;
            for (int x = 0; x < width; x += 4)
            {
                unsigned int b1 = 0, b2 = 0;
                if (kind == ETC_ETC2_RGBA8)
                {
                    if (slow)
                        compressBlockAlphaSlow(alpha, x, y, width, height, p);
                    else
                        compressBlockAlphaFast(alpha, x, y, width, height, p);
                    p += 8;
                }
                if (kind == ETC_ETC1)
                {
                    if (perceptual)
                        slow ? compressBlockETC1ExhaustivePerceptual(img, imgdec, width, height, x, y, b1, b2)
                             : compressBlockDiffFlipFastPerceptual(img, imgdec, width, height, x, y, b1, b2);
                    else if (slow)
                        compressBlockETC1Exhaustive(img, imgdec, width, height, x, y, b1, b2);
                    else
                        compressBlockDiffFlipFast(img, imgdec, width, height, x, y, b1, b2);
                }
                else
                {
                    if (perceptual)
                        slow ? compressBlockETC2ExhaustivePerceptual(img, imgdec, width, height, x, y, b1, b2)
                             : compressBlockETC2FastPerceptual(img, imgdec, width, height, x, y, b1, b2);
                    else if (slow)
                        compressBlockETC2Exhaustive(img, imgdec, width, height, x, y, b1, b2);
                    else
                        compressBlockETC2Fast(img, alpha, imgdec, width, height, x, y, b1, b2);
                }
                put_be(p, b1);
                put_be(p + 4, b2);
                p += 8;
            }
        }
    };
    int count = threads > 0 ? threads : (int)std::thread::hardware_concurrency();
    if (count < 1)
        count = 1;
    if (count > rows)
        count = rows;
    std::vector<std::thread> pool;
    for (int i = 1; i < count; i++)
        pool.emplace_back(work);
    work();
    for (auto &t : pool)
        t.join();

    free(img);
    free(imgdec);
    free(alpha);
    return blocks * block_size;
}
