/* Synthetic Linux filesystem faults, loaded only into an isolated test worker.
 * Rust 1.99 uses statx/readlink here; missing hooks fail the hit assertions. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int selected(const char *op, const char *path) {
    static unsigned seen;
    const char *wanted_op = getenv("synthetic_locate_op");
    const char *wanted_path = getenv("synthetic_locate_path");
    if (!path || !wanted_op || !wanted_path || strcmp(op, wanted_op) || strcmp(path, wanted_path)) return 0;
    return ++seen == strtoul(getenv("synthetic_locate_occurrence"), NULL, 10);
}
static void record(const char *text) {
    const char mode[] = {'a', 0};
    FILE *log = fopen(getenv("synthetic_locate_log"), mode);
    if (!log || fputs(text, log) < 0 || fputc('\n', log) == EOF || fclose(log)) _exit(98);
}
static int fault(void) {
    const char *kind = getenv("synthetic_locate_fault");
    int code = !strcmp(kind, "synthetic-missing") ? ENOENT : !strcmp(kind, "synthetic-denied") ? EACCES :
               !strcmp(kind, "synthetic-invalid") ? EINVAL : !strcmp(kind, "synthetic-io") ? EIO : 0;
    if (code) {
        record(kind);
        errno = code;
    }
    return code;
}
int statx(int fd, const char *path, int flags, unsigned mask, struct statx *out) {
    int (*original)(int, const char *, int, unsigned, struct statx *) = dlsym(RTLD_NEXT, __func__);
    int hit = selected("synthetic-statx", path);
    if (hit && fault()) return -1;
    int result = original(fd, path, flags, mask, out);
    if (hit) {
        if (result) _exit(97);
        unsigned dev = out->stx_dev_major;
        unsigned long long ino = out->stx_ino;
        const char *kind = getenv("synthetic_locate_fault");
        if (strstr(kind, "synthetic-device")) out->stx_dev_major ^= 1;
        if (strstr(kind, "synthetic-inode") || !strcmp(kind, "synthetic-device-inode")) out->stx_ino ^= 1;
        char line[160];
        snprintf(line, sizeof(line), "synthetic %u %llu %u %llu", dev, ino,
                 out->stx_dev_major, (unsigned long long)out->stx_ino);
        record(line);
    }
    return result;
}
ssize_t readlink(const char *path, char *out, size_t size) {
    ssize_t (*original)(const char *, char *, size_t) = dlsym(RTLD_NEXT, __func__);
    if (selected("synthetic-readlink", path) && fault()) return -1;
    return original(path, out, size);
}
