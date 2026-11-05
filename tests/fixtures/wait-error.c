/* "Synthetic Linux-only wait failure": loaded only into an isolated test process.
 * Reap the started child first so its marker is complete before ECHILD, and
 * leave blocking waits alone so the runner's cleanup cannot strand a child.
 * No CloudRoom process or receipt shape is modelled here.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <sys/wait.h>

pid_t waitpid(pid_t pid, int *status, int options) {
    pid_t (*real_waitpid)(pid_t, int *, int) = dlsym(RTLD_NEXT, __func__);
    if (pid > 0 && (options & WNOHANG)) {
        real_waitpid(pid, status, options & ~WNOHANG);
        errno = ECHILD;
        return -1;
    }
    return real_waitpid(pid, status, options);
}
