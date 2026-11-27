#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <assert.h>

extern char **environ;

/* Read by ref-utils (`get_user_environment()`) to restore the caller's
 * environment for programs the submission tests run with dropped privileges. */
const char *env_dump_path = "/tmp/.user_environ";

/* A copy kept in the persisted home directory, so a submission records the
 * environment the student last ran `task` with. Informational only: the
 * student can write this file at will, so nothing may trust its content. */
const char *env_snapshot_path = "/home/user/.user_environ";

const char *is_submission_marker = "/etc/is_submission";

#define FATAL_ERROR() { printf("[!] ERROR: please contact your system administrator (code=%u)\n", __LINE__); exit(1); };

/*
 * Write every environment variable, each terminated by a NUL byte, to `fd`.
 * Closes `fd`. Returns 0 on success, -1 on error.
 */
static int dump_environ_to_fd(int fd)
{
    FILE *f = fdopen(fd, "w");
    if (!f) {
        close(fd);
        return -1;
    }

    for (char **env = environ; *env; env++) {
        /* Include the NUL byte, which the reader uses as delimiter. */
        if (fwrite(*env, strlen(*env) + 1, 1, f) != 1) {
            fclose(f);
            return -1;
        }
    }

    return fclose(f) == 0 ? 0 : -1;
}

int main(int argc, char const *argv[])
{
    int fd;

    /*
     * This program is not setuid; everything up to the execv below runs with
     * the caller's privileges, so these writes can only touch files the caller
     * could write anyway. O_NOFOLLOW still matters when an admin runs `task`
     * as root inside a student's instance: the student controls both paths and
     * could otherwise point them at any file via a symlink.
     */
    fd = open(env_dump_path, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0644);
    if (fd < 0 || dump_environ_to_fd(fd) != 0) {
        printf("[!] Error while dumping environment to %s: %s\n", env_dump_path, strerror(errno));
        FATAL_ERROR();
    }

    /*
     * Only snapshot the student's own environment, and never in a submission,
     * where the snapshot taken at submission time must survive. A failure is
     * not fatal: the snapshot is informational and must not block `task`.
     */
    if (geteuid() != 0 && access(is_submission_marker, F_OK) != 0) {
        /* Replace rather than truncate, so a FIFO or symlink the student left
         * at this path does not block or fail the write. If unlink fails, the
         * O_EXCL open below fails too and reports it. */
        (void)unlink(env_snapshot_path);
        fd = open(env_snapshot_path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0644);
        if (fd < 0 || dump_environ_to_fd(fd) != 0) {
            printf("[!] Warning: could not save environment snapshot to %s: %s\n",
                   env_snapshot_path, strerror(errno));
        }
    }

    /* Execute the actual task script  */

    if (argc == 0) {
        printf("[!] Insufficient number of arguments\n");
        exit(1);
    }

    assert(argc > 0);

    int new_argc = argc;
    new_argc -=1; /* We do not care about argv[0] */
    new_argc += 1; /* /usr/bin/sudo */
    new_argc += 1; /* /usr/local/bin/_task */
    new_argc += 1; /* NULL */

    char *new_argv[new_argc];
    new_argv[0] = "/usr/bin/sudo";
    new_argv[1] = "/usr/local/bin/_task";
    new_argv[new_argc-1] = NULL; /* Terminate the array with NULL */

    if (argc > 1) {
        for (int i = 0; i < argc-1; i++) {
            /* We are fine with discarding the const here */
            new_argv[i+2] = (char*)argv[i+1];
        }
    }

    execv("/usr/bin/sudo", new_argv);

    printf("[!] Error calling execv\n");
    FATAL_ERROR();
}
