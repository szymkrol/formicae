// rng.hpp - deterministic PCG32 random generator (spec section 3). Owner: P1 (M1).
#pragma once
#include <cstdint>

namespace formicae {

class Rng {
 public:
  explicit Rng(uint64_t seed = 0, uint64_t stream = 1) { reseed(seed, stream); }

  void reseed(uint64_t seed, uint64_t stream = 1) {
    state_ = 0;
    inc_ = (stream << 1u) | 1u;
    next_u32();
    state_ += seed;
    next_u32();
  }

  uint32_t next_u32() {
    const uint64_t old = state_;
    state_ = old * 6364136223846793005ULL + inc_;
    const uint32_t xorshifted = static_cast<uint32_t>(((old >> 18u) ^ old) >> 27u);
    const uint32_t rot = static_cast<uint32_t>(old >> 59u);
    return (xorshifted >> rot) | (xorshifted << ((~rot + 1u) & 31u));
  }

  float next_float() { return static_cast<float>(next_u32() >> 8) * (1.0f / 16777216.0f); }  // [0, 1)
  int next_int(int n) { return static_cast<int>((static_cast<uint64_t>(next_u32()) * static_cast<uint64_t>(n)) >> 32); }  // [0, n)

  // For save/load and determinism hashes.
  uint64_t state() const { return state_; }
  uint64_t inc() const { return inc_; }
  void restore(uint64_t state, uint64_t inc) { state_ = state; inc_ = inc; }

 private:
  uint64_t state_ = 0;
  uint64_t inc_ = 1;
};

}  // namespace formicae
