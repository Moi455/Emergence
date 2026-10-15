/* C interface of the tok-2 tokenizer (T28): the SAME code in the game and in the training (ctypes from Python).
 *
 * Ownership: the caller owns every buffer it passes; the library owns the handle (em_tok2_create/destroy). One handle
 * per thread (it holds a scratch and a memo of validated propositions); the tokenizer inside is immutable.
 * The arrays of a decision go into ONE caller buffer of em_tok2_buffer_size() bytes, tightly packed, in the order of
 * Encoded.ARRAYS of the oracle (type_id, num, known, cat, cat_known, ptr, ptr_known, prop_sym, prop_arity, prop_depth,
 * prop_slot, prop_num) with the shapes/dtypes em_tok2_array_* gives; num and prop_num are binary16 bits (uint16).
 * No function throws or aborts; an error is a nonzero return and a message in the caller's buffer.
 */
#ifndef EMERGENCE_TOKENIZER_CAPI_H
#define EMERGENCE_TOKENIZER_CAPI_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct em_tok2 em_tok2;   /* opaque */

typedef struct em_tok2_info {
  uint32_t n;          /* number of tokens (rows used) */
  uint32_t digest;     /* crc32 chain of Encoded.digest() */
  uint32_t n_ghosts;   /* distinct ghosts numbered (<= 32 plus the overflow ones counted up to 32) */
  uint32_t reserved;
} em_tok2_info;

em_tok2* em_tok2_create(void);
void em_tok2_destroy(em_tok2*);

/* identity of the format: must equal the Python Tokenizer's header/fingerprints */
uint64_t em_tok2_layout_fingerprint(void);
uint64_t em_tok2_interface_fingerprint(void);
uint64_t em_tok2_vocab_fingerprint(void);

/* layout of the output buffer */
size_t em_tok2_buffer_size(void);
int em_tok2_array_count(void);
const char* em_tok2_array_name(int i);
size_t em_tok2_array_offset(int i);
size_t em_tok2_array_bytes(int i);
int em_tok2_array_itemsize(int i);   /* 1, 2 */
int em_tok2_array_rows(void);        /* 128 */
int em_tok2_array_cols(int i);       /* 0 for type_id, else the width */

/* Encodes one DecisionContext in canonical JSON. 0 = ok; 1 = refused (TokenError message in err); 2 = bad argument. */
int em_tok2_encode_json(em_tok2*, const char* json, size_t len, void* buffer, em_tok2_info* info, char* err, size_t err_cap);

/* Encodes `count` contexts: jsons[i]/lens[i] -> buffer + i * em_tok2_buffer_size(); status[i] is 0 or 1; infos[i].
 * Returns the number of contexts encoded without refusal. Errors are not detailed (use em_tok2_encode_json). */
int em_tok2_encode_batch(em_tok2*, const char* const* jsons, const size_t* lens, int count, void* buffers,
                         em_tok2_info* infos, int* status);

/* Feasibility mask of an encoded decision (read from `buffer`, the arrays above, never from the world).
 * out_gesture: 40 bytes (1 = feasible). out_refs: 40 * 3 * 129 bytes (gesture, k-th pointer, nobody/slot 1..128),
 * flags: 40 * 3 bytes (bit 0 used, bit 1 optional, bit 2 accepts a direction, bit 3 accepts a form). */
int em_tok2_feasibility(em_tok2*, const void* buffer, uint32_t n, uint8_t* out_gesture, uint8_t* out_refs, uint8_t* out_flags);
int em_tok2_gesture_count(void);
const char* em_tok2_gesture_name(int g);

/* small helpers exposed for parity tests */
uint16_t em_tok2_to_half(double x);   /* binary16 bits, one rounding, +0 for a zero */
uint32_t em_tok2_crc32(uint32_t crc, const void* data, size_t len);

#ifdef __cplusplus
}
#endif
#endif
