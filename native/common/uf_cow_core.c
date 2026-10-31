/*
 * In-memory sector CoW reference implementation for UserFreezer.
 * Does NOT interact with FltMgr, Win32, disks or original binaries.
 */
#include "uf_cow_core.h"

#include <stdint.h>
#include <string.h>

static int uf_ranges_overlap(
    const void *left, size_t left_size,
    const void *right, size_t right_size)
{
    uintptr_t a;
    uintptr_t b;
    if (left_size == 0 || right_size == 0) {
        return 0;
    }
    a = (uintptr_t)left;
    b = (uintptr_t)right;
    if (a <= b) {
        return (b - a) < left_size;
    }
    return (a - b) < right_size;
}

static int uf_valid_volume(const struct uf_cow_volume *volume)
{
    if (!volume || !volume->baseline || !volume->overlay ||
        !volume->dirty_sectors ||
        volume->sector_size < 512 || volume->sector_size > 4096 ||
        (volume->sector_size & (volume->sector_size - 1)) != 0 ||
        volume->bytes == 0 ||
        (volume->bytes % volume->sector_size) != 0 ||
        volume->sector_count != volume->bytes / volume->sector_size ||
        volume->max_dirty_sectors == 0 ||
        volume->max_dirty_sectors > volume->sector_count ||
        volume->dirty_count > volume->max_dirty_sectors) {
        return 0;
    }
    return 1;
}

static int uf_allowed_range(
    const struct uf_cow_volume *volume, size_t offset, size_t bytes)
{
    if (offset > volume->bytes || bytes > volume->bytes - offset) {
        return 0;
    }
    return 1;
}

static int uf_external_bytes(
    const struct uf_cow_volume *volume, const uint8_t *external,
    size_t length)
{
    if (length == 0) {
        return 1;
    }
    if (!external ||
        uf_ranges_overlap(external, length, volume->baseline, volume->bytes) ||
        uf_ranges_overlap(external, length, volume->overlay, volume->bytes) ||
        uf_ranges_overlap(external, length,
                          volume->dirty_sectors, volume->sector_count)) {
        return 0;
    }
    return 1;
}

int uf_cow_init(
    struct uf_cow_volume *volume,
    const uint8_t *baseline, size_t baseline_bytes,
    size_t sector_bytes, uint8_t *overlay, size_t overlay_bytes,
    uint8_t *dirty_map, size_t dirty_map_bytes,
    size_t max_dirty_sectors)
{
    size_t sectors;
    if (!volume || !baseline || !overlay || !dirty_map ||
        sector_bytes < 512 || sector_bytes > 4096 ||
        (sector_bytes & (sector_bytes - 1)) != 0 ||
        baseline_bytes == 0 || (baseline_bytes % sector_bytes) != 0 ||
        overlay_bytes < baseline_bytes) {
        return UF_COW_INVALID;
    }

    sectors = baseline_bytes / sector_bytes;
    if (dirty_map_bytes < sectors || max_dirty_sectors == 0 ||
        max_dirty_sectors > sectors ||
        uf_ranges_overlap(baseline, baseline_bytes, overlay, baseline_bytes) ||
        uf_ranges_overlap(baseline, baseline_bytes, dirty_map, sectors) ||
        uf_ranges_overlap(overlay, baseline_bytes, dirty_map, sectors)) {
        return UF_COW_INVALID;
    }
    /* Caller holds the only mutable copies. No memory allocation. */
    memset(overlay, 0, baseline_bytes);
    memset(dirty_map, 0, sectors);
    volume->baseline = baseline;
    volume->overlay = overlay;
    volume->dirty_sectors = dirty_map;
    volume->bytes = baseline_bytes;
    volume->sector_size = sector_bytes;
    volume->sector_count = sectors;
    volume->max_dirty_sectors = max_dirty_sectors;
    volume->dirty_count = 0;
    return UF_COW_OK;
}

int uf_cow_read(
    const struct uf_cow_volume *volume,
    size_t offset, uint8_t *destination, size_t bytes)
{
    size_t position = offset;
    size_t remaining = bytes;
    if (!uf_valid_volume(volume)) {
        return UF_COW_INVALID;
    }
    if (!uf_allowed_range(volume, offset, bytes)) {
        return UF_COW_RANGE;
    }
    if (!uf_external_bytes(volume, destination, bytes)) {
        return UF_COW_INVALID;
    }
    /* Validate complete read range before writing anything to caller. */
    while (remaining != 0) {
        size_t sector = position / volume->sector_size;
        size_t chunk = volume->sector_size - position % volume->sector_size;
        if (volume->dirty_sectors[sector] > 1) {
            return UF_COW_STATE;
        }
        if (chunk > remaining) {
            chunk = remaining;
        }
        position += chunk;
        remaining -= chunk;
    }
    position = offset;
    remaining = bytes;
    while (remaining != 0) {
        size_t sector = position / volume->sector_size;
        size_t chunk = volume->sector_size - position % volume->sector_size;
        const uint8_t *source = volume->dirty_sectors[sector] ?
            volume->overlay : volume->baseline;
        if (chunk > remaining) {
            chunk = remaining;
        }
        memcpy(destination + (position - offset), source + position, chunk);
        position += chunk;
        remaining -= chunk;
    }
    return UF_COW_OK;
}

int uf_cow_write(
    struct uf_cow_volume *volume,
    size_t offset, const uint8_t *source, size_t bytes)
{
    size_t position = offset;
    size_t remaining = bytes;
    size_t first;
    size_t last;
    size_t i;
    size_t needed = 0;

    if (!uf_valid_volume(volume)) {
        return UF_COW_INVALID;
    }
    if (!uf_allowed_range(volume, offset, bytes)) {
        return UF_COW_RANGE;
    }
    if (!uf_external_bytes(volume, source, bytes)) {
        return UF_COW_INVALID;
    }
    if (bytes == 0) {
        return UF_COW_OK;
    }

    /* Full preflight: no changes when capacity or bitmap is invalid. */
    first = offset / volume->sector_size;
    last = (offset + bytes - 1) / volume->sector_size;
    for (i = first; i <= last; ++i) {
        uint8_t mark = volume->dirty_sectors[i];
        if (mark > 1) {
            return UF_COW_STATE;
        }
        if (mark == 0) {
            ++needed;
        }
    }
    if (needed > volume->max_dirty_sectors - volume->dirty_count) {
        return UF_COW_CAPACITY;
    }

    while (remaining != 0) {
        size_t sector = position / volume->sector_size;
        size_t begin = sector * volume->sector_size;
        size_t chunk = volume->sector_size - position % volume->sector_size;
        if (chunk > remaining) {
            chunk = remaining;
        }
        if (volume->dirty_sectors[sector] == 0) {
            memcpy(volume->overlay + begin,
                   volume->baseline + begin, volume->sector_size);
            volume->dirty_sectors[sector] = 1;
            ++volume->dirty_count;
        }
        memcpy(volume->overlay + position,
               source + (position - offset), chunk);
        remaining -= chunk;
        position += chunk;
    }
    return UF_COW_OK;
}

int uf_cow_discard(struct uf_cow_volume *volume)
{
    if (!uf_valid_volume(volume)) {
        return UF_COW_INVALID;
    }
    /* No physical disk, no journal, no boot interception. */
    memset(volume->overlay, 0, volume->bytes);
    memset(volume->dirty_sectors, 0, volume->sector_count);
    volume->dirty_count = 0;
    return UF_COW_OK;
}
