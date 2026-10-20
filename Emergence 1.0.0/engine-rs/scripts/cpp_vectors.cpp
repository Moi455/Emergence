// Génère les vecteurs de parité Rust/C++ de em_core : inclut les VRAIS en-têtes du moteur
// (engine/core/base hash.h et fixed.h, engine/ops digest, engine/act entity_id.h) et imprime
// un fichier Rust de constantes. Lancé par engine-rs/scripts/gen_cpp_vectors.sh ; ne pas éditer la sortie.
// Les entrées sont déterministes (chaîne mix64) et restent dans le domaine où le C++ est défini :
// qmul |a*b| < 2^63, qdiv |a*65536| < 2^63, qsmoothstep |(x-e0)*65536| < 2^63.
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "emergence/act/entity_id.h"
#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/ops/digest.h"

using namespace em;

static uint64_t g_etat = 0x5eed1e5ULL;
static uint64_t tirage() { return g_etat = mix64(g_etat + 0x9e3779b97f4a7c15ULL); }
// Entier signé d'amplitude 2^bits au plus, avec des magnitudes variées.
static int64_t signe(int bits) {
  uint64_t r = tirage();
  int b = 1 + static_cast<int>(r % bits);
  int64_t v = static_cast<int64_t>(tirage() >> (64 - b));
  return (tirage() & 1) ? -v : v;
}

static void tete(const char* nom, const char* type, size_t n) { std::printf("pub const %s: [%s; %zu] = [\n", nom, type, n); }
static void queue() { std::printf("];\n\n"); }

int main() {
  std::printf("// FICHIER GÉNÉRÉ par engine-rs/scripts/gen_cpp_vectors.sh depuis le C++ : ne pas éditer.\n");
  std::printf("// Source : engine/core/base (hash.h, fixed.h), engine/ops (digest), engine/act (entity_id.h).\n\n");

  // mix64 : 10 valeurs.
  const uint64_t m_in[10] = {0, 1, 2, 3, 0xdeadbeefULL, 0x8000000000000000ULL, UINT64_MAX, 0x123456789abcdef0ULL, 42, 1000000007ULL};
  tete("MIX64", "(u64, u64)", 10);
  for (uint64_t x : m_in) std::printf("    (%#llxu64, %#llxu64),\n", (unsigned long long)x, (unsigned long long)mix64(x));
  queue();

  // hash_combine, hash2.
  tete("HASH_COMBINE", "(u64, u64, u64)", 8);
  for (int i = 0; i < 8; ++i) { uint64_t h = tirage(), v = i == 0 ? UINT64_MAX : tirage();
    std::printf("    (%#llxu64, %#llxu64, %#llxu64),\n", (unsigned long long)h, (unsigned long long)v, (unsigned long long)hash_combine(h, v)); }
  queue();
  tete("HASH2", "(u64, i64, i64, u64)", 12);
  for (int i = 0; i < 12; ++i) { uint64_t s = i == 0 ? UINT64_MAX : tirage(); int64_t x = signe(40), y = signe(40);
    std::printf("    (%#llxu64, %lldi64, %lldi64, %#llxu64),\n", (unsigned long long)s, (long long)x, (long long)y, (unsigned long long)hash2(s, x, y)); }
  queue();

  // hash3 : dont graine UINT64_MAX et coordonnées négatives.
  tete("HASH3", "(u64, i64, i64, i64, u64)", 20);
  for (int i = 0; i < 20; ++i) {
    uint64_t s = i < 2 ? UINT64_MAX : (i == 2 ? 0 : tirage());
    int64_t x = i == 1 ? -1 : signe(40), y = i == 1 ? -1 : signe(40), z = i == 1 ? -1 : signe(40);
    if (i == 3) { x = INT64_MIN; y = INT64_MAX; z = -400000; }
    std::printf("    (%#llxu64, %lldi64, %lldi64, %lldi64, %#llxu64),\n", (unsigned long long)s, (long long)x, (long long)y, (long long)z, (unsigned long long)hash3(s, x, y, z));
  }
  queue();

  // layer_seed : chaque couche x 3 graines.
  tete("LAYER_SEED", "(u64, u64, u64)", 13 * 3);
  const uint64_t graines[3] = {0, 42, UINT64_MAX};
  for (uint64_t s : graines)
    for (uint64_t l = 1; l <= 13; ++l)
      std::printf("    (%#llxu64, %lluu64, %#llxu64),\n", (unsigned long long)s, (unsigned long long)l, (unsigned long long)layer_seed(s, static_cast<Layer>(l)));
  queue();

  // SplitMix64 (formule : état += 0x9e37..., sortie mix64(état)) : 8 sorties pour 2 graines.
  tete("SPLITMIX", "(u64, u64)", 16);
  for (uint64_t s : {uint64_t{0}, uint64_t{0x123456789ULL}}) { uint64_t e = s; for (int i = 0; i < 8; ++i) { e += 0x9e3779b97f4a7c15ULL;
    std::printf("    (%#llxu64, %#llxu64),\n", (unsigned long long)s, (unsigned long long)mix64(e)); } }
  queue();

  // Fixed-point : 100 entrées chacun.
  tete("QMUL", "(i64, i64, i64)", 100);
  for (int i = 0; i < 100; ++i) { int64_t a = signe(31), b = signe(31); if (i == 0) { a = 65536; b = 65536; } if (i == 1) { a = -65536; b = 32768; }
    std::printf("    (%lldi64, %lldi64, %lldi64),\n", (long long)a, (long long)b, (long long)qmul(a, b)); }
  queue();
  tete("QDIV", "(i64, i64, i64)", 100);
  for (int i = 0; i < 100; ++i) { int64_t a = signe(46), b = signe(40); if (b == 0) b = 3; if (i == 0) { a = 65536; b = 131072; } if (i == 1) { a = -7; b = 2; }
    std::printf("    (%lldi64, %lldi64, %lldi64),\n", (long long)a, (long long)b, (long long)qdiv(a, b)); }
  queue();
  tete("QLERP", "(i64, i64, i64, i64)", 50);
  for (int i = 0; i < 50; ++i) { int64_t a = signe(30), b = signe(30), t = tirage() % 65537;
    std::printf("    (%lldi64, %lldi64, %lldi64, %lldi64),\n", (long long)a, (long long)b, (long long)t, (long long)qlerp(a, b, t)); }
  queue();
  tete("QSMOOTHSTEP", "(i64, i64, i64, i64)", 100);
  for (int i = 0; i < 100; ++i) { int64_t e0 = signe(30), w = 1 + static_cast<int64_t>(tirage() % (1ULL << (1 + tirage() % 30))); int64_t e1 = e0 + w;
    int64_t x = e0 + signe(31) % (2 * w + 1) - w / 2; if (i % 10 == 0) x = e0; if (i % 10 == 1) x = e1;
    std::printf("    (%lldi64, %lldi64, %lldi64, %lldi64),\n", (long long)e0, (long long)e1, (long long)x, (long long)qsmoothstep(e0, e1, x)); }
  queue();
  tete("QRAMP", "(i64, i64, i64, i64)", 50);
  for (int i = 0; i < 50; ++i) { int64_t e0 = signe(30), w = 1 + static_cast<int64_t>(tirage() % (1ULL << (1 + tirage() % 30))); int64_t e1 = e0 + w;
    int64_t x = e0 + signe(31) % (2 * w + 1) - w / 2;
    std::printf("    (%lldi64, %lldi64, %lldi64, %lldi64),\n", (long long)e0, (long long)e1, (long long)x, (long long)qramp(e0, e1, x)); }
  queue();
  tete("QEXP2", "(i64, i64)", 100);
  for (int i = 0; i < 100; ++i) { int64_t x = static_cast<int64_t>(tirage() % (92ULL << 16)) - (46LL << 16); if (i == 0) x = 0; if (i == 1) x = 65536; if (i == 2) x = -65536;
    if (i == 3) x = 41LL << 16; if (i == 4) x = 40LL << 16; if (i == 5) x = -(41LL << 16); if (i == 6) x = -(40LL << 16) - 1;
    std::printf("    (%lldi64, %lldi64),\n", (long long)x, (long long)qexp2(x)); }
  queue();
  tete("ISQRT64", "(u64, u64)", 100);
  for (int i = 0; i < 100; ++i) { uint64_t v = tirage() >> (tirage() % 64); if (i == 0) v = 0; if (i == 1) v = UINT64_MAX; if (i == 2) v = 1; if (i == 3) v = 4294967295ULL * 4294967295ULL;
    if (i == 4) v = 4294967295ULL * 4294967295ULL - 1; if (i >= 90) { uint64_t r = tirage() >> 33; v = r * r + (i % 2 ? 0 : r); }
    std::printf("    (%lluu64, %lluu64),\n", (unsigned long long)v, (unsigned long long)isqrt64(v)); }
  queue();
  tete("FLOOR_DIV", "(i64, i64, i64)", 40);
  for (int i = 0; i < 40; ++i) { int64_t a = signe(40), b = signe(12); if (b == 0) b = -64; if (i == 0) { a = -1; b = 64; } if (i == 1) { a = -64; b = 64; } if (i == 2) { a = 65; b = -64; }
    std::printf("    (%lldi64, %lldi64, %lldi64),\n", (long long)a, (long long)b, (long long)floor_div(a, b)); }
  queue();

  // CRC32 et FNV-1a.
  const std::vector<std::string> textes = {"", "a", "abc", "123456789", "Emergence 1.0.0", std::string("\x00\xff\x01\x80", 4), "The quick brown fox jumps over the lazy dog"};
  std::printf("pub const CRC32: [(&[u8], u32); %zu] = [\n", textes.size());
  for (const auto& t : textes) { std::printf("    (&["); for (unsigned char c : t) std::printf("%u,", c);
    std::printf("], %#xu32),\n", ops::crc32(std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(t.data()), t.size()))); }
  queue();
  std::printf("pub const FNV64: [(&[u8], u64); %zu] = [\n", textes.size());
  for (const auto& t : textes) { ops::Fnv64 f; f.add(std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(t.data()), t.size()));
    std::printf("    (&["); for (unsigned char c : t) std::printf("%u,", c); std::printf("], %#llxu64),\n", (unsigned long long)f.value()); }
  queue();
  // FNV avec add_u64 mélangé : (octets préfixe, u64 ajouté, valeur finale).
  tete("FNV64_U64", "(u64, u64)", 6);
  for (int i = 0; i < 6; ++i) { uint64_t v = i == 0 ? 0 : (i == 1 ? UINT64_MAX : tirage()); ops::Fnv64 f; f.add_u64(v); f.add_u64(7);
    std::printf("    (%#llxu64, %#llxu64),\n", (unsigned long long)v, (unsigned long long)f.value()); }
  queue();

  // EntityId : (case, génération, brut).
  tete("ENTITY_ID", "(u32, u32, u32)", 8);
  const uint32_t cas[8][2] = {{1, 0}, {1, 1}, {4194303, 1023}, {2, 0}, {123456, 7}, {77, 1023}, {4194303, 0}, {1000, 512}};
  for (auto& c : cas) { act::EntityId id = act::make_entity_id(c[0], c[1]);
    if (act::index_of(id) != c[0] || act::generation_of(id) != c[1]) return 1;
    std::printf("    (%u, %u, %#xu32),\n", c[0], c[1], id); }
  queue();
  return 0;
}
