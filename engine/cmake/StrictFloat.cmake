# Determinism (architecture invariant I2): world generation must be bit-exact
# on every platform. Generation code is integer-only, but we still forbid the
# options that would make any stray float non-reproducible.
function(emergence_strict_target target)
  if(MSVC)
    target_compile_options(${target} PRIVATE /W4 /fp:strict /permissive-)
  else()
    target_compile_options(${target} PRIVATE
      -Wall -Wextra -Wpedantic
      -ffp-contract=off
      -fno-fast-math
      -fno-strict-aliasing)
  endif()
endfunction()
