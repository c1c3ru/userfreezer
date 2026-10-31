/* Deterministic offline tests: no files, no drivers, no WDK needed. */
#include "uf_cow_core.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define SECTOR_BYTES 512u
#define SECTORS 4u
#define TOTAL_BYTES (SECTORS * SECTOR_BYTES)
#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "CoW FAILED line %d: %s\n", __LINE__, #expr); \
        return 1; \
    } \
} while (0)

static uint8_t original[TOTAL_BYTES];
static uint8_t scratch[TOTAL_BYTES];
static uint8_t overlay[TOTAL_BYTES];
static uint8_t marks[SECTORS];

static void prepare(void)
{
    size_t i;
    for (i = 0; i < TOTAL_BYTES; ++i) {
        original[i] = (uint8_t)((i * 17u + 31u) % 251u);
    }
    memset(scratch, 0xe1, sizeof(scratch));
    memset(overlay, 0xc4, sizeof(overlay));
    memset(marks, 0x77, sizeof(marks));
}

static int basic_copy_on_write(void)
{
    struct uf_cow_volume state;
    const uint8_t bytes[8] = { 1, 2, 3, 4, 5, 6, 7, 8 };
    uint8_t baseline_snapshot[TOTAL_BYTES];
    size_t i;

    prepare();
    memcpy(baseline_snapshot, original, TOTAL_BYTES);
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES, SECTOR_BYTES,
                      overlay, sizeof(overlay), marks, sizeof(marks),
                      SECTORS) == UF_COW_OK);
    CHECK(state.dirty_count == 0);
    CHECK(uf_cow_read(&state, 0, scratch, TOTAL_BYTES) == UF_COW_OK);
    CHECK(memcmp(scratch, original, TOTAL_BYTES) == 0);
    CHECK(uf_cow_write(&state, 509u, bytes, sizeof(bytes)) == UF_COW_OK);
    CHECK(state.dirty_count == 2);
    CHECK(uf_cow_read(&state, 509u, scratch, sizeof(bytes)) == UF_COW_OK);
    CHECK(memcmp(scratch, bytes, sizeof(bytes)) == 0);
    CHECK(memcmp(original, baseline_snapshot, TOTAL_BYTES) == 0);
    /* Full-sector copy-up makes unchanged positions visible. */
    CHECK(uf_cow_read(&state, 0, scratch, TOTAL_BYTES) == UF_COW_OK);
    for (i = 0; i < TOTAL_BYTES; ++i) {
        if (i >= 509u && i < 517u) {
            CHECK(scratch[i] == bytes[i - 509u]);
        } else {
            CHECK(scratch[i] == original[i]);
        }
    }
    /* Second write in same sectors doesn't allocate more sectors. */
    CHECK(uf_cow_write(&state, 513u, bytes, 2) == UF_COW_OK);
    CHECK(state.dirty_count == 2);
    CHECK(uf_cow_discard(&state) == UF_COW_OK);
    CHECK(state.dirty_count == 0);
    CHECK(uf_cow_read(&state, 0, scratch, TOTAL_BYTES) == UF_COW_OK);
    CHECK(memcmp(scratch, original, TOTAL_BYTES) == 0);
    for (i = 0; i < TOTAL_BYTES; ++i) {
        CHECK(overlay[i] == 0);
    }
    CHECK(memcmp(original, baseline_snapshot, TOTAL_BYTES) == 0);
    return 0;
}

static int preflight_capacity_atomicity(void)
{
    struct uf_cow_volume state;
    const uint8_t bytes[6] = { 1, 2, 3, 4, 5, 6 };
    uint8_t snapshot[TOTAL_BYTES];
    uint8_t marker_snapshot[SECTORS];

    prepare();
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES, SECTOR_BYTES,
                      overlay, sizeof(overlay), marks, sizeof(marks),
                      2) == UF_COW_OK);
    CHECK(uf_cow_write(&state, 512, bytes, 1) == UF_COW_OK);
    CHECK(state.dirty_count == 1);
    memcpy(snapshot, overlay, sizeof(overlay));
    memcpy(marker_snapshot, marks, sizeof(marks));

    /* Would touch two new sectors; caller must see all-or-nothing. */
    CHECK(uf_cow_write(&state, 1022, bytes, sizeof(bytes)) ==
          UF_COW_CAPACITY);
    CHECK(state.dirty_count == 1);
    CHECK(memcmp(overlay, snapshot, sizeof(overlay)) == 0);
    CHECK(memcmp(marks, marker_snapshot, sizeof(marks)) == 0);
    CHECK(uf_cow_write(&state, 0, bytes, 1) == UF_COW_OK);
    CHECK(state.dirty_count == 2);
    CHECK(uf_cow_write(&state, 1536, bytes, 1) == UF_COW_CAPACITY);
    CHECK(uf_cow_read(&state, 1536, scratch, 1) == UF_COW_OK);
    CHECK(scratch[0] == original[1536]);
    return 0;
}

static int malformed_access_and_alias(void)
{
    struct uf_cow_volume state;
    uint8_t sample[16] = { 0 };
    uint8_t unmodified[16];
    size_t size_max = (size_t)-1;

    prepare();
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES, SECTOR_BYTES,
                      overlay, sizeof(overlay), marks, sizeof(marks),
                      SECTORS) == UF_COW_OK);
    CHECK(uf_cow_write(&state, 2047, sample, sizeof(sample)) == UF_COW_RANGE);
    CHECK(uf_cow_write(&state, size_max, sample, 2) == UF_COW_RANGE);
    CHECK(uf_cow_read(&state, 2047, sample, 2) == UF_COW_RANGE);
    CHECK(uf_cow_read(&state, size_max, sample, 2) == UF_COW_RANGE);
    CHECK(uf_cow_read(&state, TOTAL_BYTES, NULL, 0) == UF_COW_OK);
    CHECK(uf_cow_write(&state, TOTAL_BYTES, NULL, 0) == UF_COW_OK);
    CHECK(uf_cow_write(&state, 0, original, 1) == UF_COW_INVALID);
    CHECK(uf_cow_write(&state, 0, overlay, 1) == UF_COW_INVALID);
    CHECK(uf_cow_read(&state, 0, overlay, 1) == UF_COW_INVALID);
    CHECK(uf_cow_read(&state, 0, marks, 1) == UF_COW_INVALID);
    CHECK(state.dirty_count == 0);

    memset(sample, 0x5a, sizeof(sample));
    memcpy(unmodified, sample, sizeof(sample));
    marks[0] = 2; /* Simulated corrupted in-memory state. */
    CHECK(uf_cow_read(&state, 0, sample, 1) == UF_COW_STATE);
    CHECK(uf_cow_write(&state, 0, sample, 1) == UF_COW_STATE);
    CHECK(memcmp(sample, unmodified, sizeof(sample)) == 0);
    CHECK(state.dirty_count == 0);
    CHECK(uf_cow_discard(&state) == UF_COW_OK);
    CHECK(marks[0] == 0);
    return 0;
}

static int initialization_validation(void)
{
    struct uf_cow_volume state;
    prepare();
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES, 0,
                      overlay, sizeof(overlay), marks, sizeof(marks),
                      SECTORS) == UF_COW_INVALID);
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES, 256,
                      overlay, sizeof(overlay), marks, sizeof(marks),
                      SECTORS) == UF_COW_INVALID);
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES-1, SECTOR_BYTES,
                      overlay, sizeof(overlay), marks, sizeof(marks),
                      SECTORS) == UF_COW_INVALID);
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES, SECTOR_BYTES,
                      overlay, TOTAL_BYTES-1, marks, sizeof(marks),
                      SECTORS) == UF_COW_INVALID);
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES, SECTOR_BYTES,
                      overlay, sizeof(overlay), marks, sizeof(marks)-1,
                      SECTORS) == UF_COW_INVALID);
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES, SECTOR_BYTES,
                      overlay, sizeof(overlay), marks, sizeof(marks),
                      0) == UF_COW_INVALID);
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES, SECTOR_BYTES,
                      overlay, sizeof(overlay), marks, sizeof(marks),
                      SECTORS+1) == UF_COW_INVALID);
    CHECK(uf_cow_init(&state, original, TOTAL_BYTES, SECTOR_BYTES,
                      (uint8_t *)original, sizeof(original), marks,
                      sizeof(marks), SECTORS) == UF_COW_INVALID);
    return 0;
}

int main(void)
{
    if (initialization_validation() ||
        basic_copy_on_write() ||
        preflight_capacity_atomicity() ||
        malformed_access_and_alias()) {
        return 1;
    }
    puts("UF_COW_TESTS_OK: in-memory model only; no filesystem or reboot proof");
    return 0;
}
