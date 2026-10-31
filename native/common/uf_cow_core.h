/*
 * UserFreezer Copy-on-Write — portable, sector-based IN-MEMORY proof of
 * semantics for future Windows kernel storage backend.
 *
 * NOT a minifilter, filter driver, disk driver, filesystem, persistent
 * overlay or reboot solution. No interception of operating-system writes.
 * All allocations and lifetime are caller-managed. No disk I/O.
 *
 * C99 / Windows user mode / Linux unit-test contract.
 */
#ifndef UF_COW_CORE_H
#define UF_COW_CORE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum uf_cow_result {
    UF_COW_OK = 0,
    UF_COW_INVALID = 1,
    UF_COW_RANGE = 2,
    UF_COW_CAPACITY = 3,
    UF_COW_STATE = 4
};

struct uf_cow_volume {
    const uint8_t *baseline;
    uint8_t *overlay;
    uint8_t *dirty_sectors;
    size_t bytes;
    size_t sector_size;
    size_t sector_count;
    size_t max_dirty_sectors;
    size_t dirty_count;
};

/*
 * All buffers MUST be disjoint. baseline must not change while this
 * volume is mounted. overlay has physical space for the whole baseline
 * (demonstration only); max_dirty_sectors limits logical dirtiness.
 * Initialization zeroes overlay and the dirty map.
 */
int uf_cow_init(struct uf_cow_volume *volume,
                const uint8_t *baseline, size_t baseline_bytes,
                size_t sector_bytes,
                uint8_t *overlay, size_t overlay_bytes,
                uint8_t *dirty_map, size_t dirty_map_bytes,
                size_t max_dirty_sectors);

int uf_cow_read(const struct uf_cow_volume *volume,
                size_t offset, uint8_t *destination, size_t bytes);

int uf_cow_write(struct uf_cow_volume *volume,
                 size_t offset, const uint8_t *source, size_t bytes);

/* Explicit memory-only rollback; does NOT simulate an OS reboot. */
int uf_cow_discard(struct uf_cow_volume *volume);

#ifdef __cplusplus
}
#endif

#endif
