// Minimal PNG writer (stored deflate, no dependency) for debug maps.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace em {

// rgb has width*height*3 bytes, rows top to bottom.
bool write_png_rgb(const std::string& path, int width, int height, const std::vector<uint8_t>& rgb);

}  // namespace em
