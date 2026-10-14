#include "emergence/base/image.h"

#include <array>
#include <cstdio>

namespace em {

namespace {

std::array<uint32_t, 256> make_crc_table() {
  std::array<uint32_t, 256> t{};
  for (uint32_t n = 0; n < 256; ++n) {
    uint32_t c = n;
    for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xedb88320u ^ (c >> 1) : c >> 1;
    t[n] = c;
  }
  return t;
}

uint32_t crc32(const uint8_t* data, size_t n, uint32_t crc = 0) {
  static const auto table = make_crc_table();
  crc = ~crc;
  for (size_t i = 0; i < n; ++i) crc = table[(crc ^ data[i]) & 0xff] ^ (crc >> 8);
  return ~crc;
}

void put_u32be(std::vector<uint8_t>& v, uint32_t x) {
  v.push_back(static_cast<uint8_t>(x >> 24));
  v.push_back(static_cast<uint8_t>(x >> 16));
  v.push_back(static_cast<uint8_t>(x >> 8));
  v.push_back(static_cast<uint8_t>(x));
}

void write_chunk(std::FILE* f, const char* type, const std::vector<uint8_t>& data) {
  std::vector<uint8_t> buf;
  put_u32be(buf, static_cast<uint32_t>(data.size()));
  buf.insert(buf.end(), type, type + 4);
  buf.insert(buf.end(), data.begin(), data.end());
  uint32_t crc = crc32(buf.data() + 4, buf.size() - 4);
  put_u32be(buf, crc);
  std::fwrite(buf.data(), 1, buf.size(), f);
}

}  // namespace

bool write_png_rgb(const std::string& path, int width, int height, const std::vector<uint8_t>& rgb) {
  std::FILE* f = std::fopen(path.c_str(), "wb");
  if (!f) return false;
  static const uint8_t sig[8] = {137, 80, 78, 71, 13, 10, 26, 10};
  std::fwrite(sig, 1, 8, f);

  std::vector<uint8_t> ihdr;
  put_u32be(ihdr, static_cast<uint32_t>(width));
  put_u32be(ihdr, static_cast<uint32_t>(height));
  ihdr.insert(ihdr.end(), {8, 2, 0, 0, 0});
  write_chunk(f, "IHDR", ihdr);

  std::vector<uint8_t> raw;
  raw.reserve(static_cast<size_t>(height) * (static_cast<size_t>(width) * 3 + 1));
  for (int y = 0; y < height; ++y) {
    raw.push_back(0);
    auto row = rgb.begin() + static_cast<long>(y) * width * 3;
    raw.insert(raw.end(), row, row + width * 3);
  }
  std::vector<uint8_t> z = {0x78, 0x01};
  uint32_t a = 1, b = 0;
  for (uint8_t c : raw) {
    a = (a + c) % 65521;
    b = (b + a) % 65521;
  }
  size_t pos = 0;
  while (pos < raw.size() || pos == 0) {
    size_t n = raw.size() - pos;
    if (n > 65535) n = 65535;
    bool last = pos + n >= raw.size();
    z.push_back(last ? 1 : 0);
    z.push_back(static_cast<uint8_t>(n));
    z.push_back(static_cast<uint8_t>(n >> 8));
    z.push_back(static_cast<uint8_t>(~n));
    z.push_back(static_cast<uint8_t>(~n >> 8));
    z.insert(z.end(), raw.begin() + static_cast<long>(pos), raw.begin() + static_cast<long>(pos + n));
    pos += n;
    if (last) break;
  }
  put_u32be(z, (b << 16) | a);
  write_chunk(f, "IDAT", z);
  write_chunk(f, "IEND", {});
  return std::fclose(f) == 0;
}

}  // namespace em
