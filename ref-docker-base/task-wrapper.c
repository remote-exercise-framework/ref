#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <assert.h>
#include <sys/personality.h>

extern char **environ;
const char *env_dump_path = "/tmp/.user_environ";

#define FATAL_ERROR() { printf("[!] ERROR: please contact your system administrator (code=%u)\n", __LINE__); exit(1); };

int main(int argc, char const *argv[])
{
    char **env = environ;
    FILE *f;

    /* Open the file we are going to dump the users environ into */
    f = fopen(env_dump_path, "w");
    if (!f) {
        printf("[!] Error while dumping environment\n");
        FATAL_ERROR();
    }

    /* Write all environments variables into the dump */
    size_t elms_written;
    while (*env) {
        /* Append a new line to each environment variable */
        char env_var[strlen(*env) + 2];
        strcpy(env_var, *env);
        strcat(env_var, "\n");

        elms_written = fwrite(env_var, strlen(env_var), 1, f);
        if (elms_written != 1) {
            printf("[!] Error while writing environment variable\n");
            FATAL_ERROR();
        }

        env++;
    }
    fclose(f);

    f = fopen("/etc/aslr_disabled", "r");
    if (!f) {
        // The current implementation of "ASLR disabling" allows users to call
        // personality(ADDR_NO_RANDOMIZE) on their own before calling task check.
        // While this is fine for non ASLR tasks, this allows users to pass task check
        // without dealing with ASLR by disabling it before calling task check.
        // To make sure that this at least does not happen by accident if, e.g.,
        // task check is called from a shell spawned in gdb (since gdb will set
        // ADDR_NO_RANDOMIZE), we reenable ASLR here.
        int ret = personality(0xffffffff);
        if (ret < 0) {
            FATAL_ERROR();
        }
        ret &= ~ADDR_NO_RANDOMIZE;
        ret = personality(ret);
        if (ret < 0) {
            FATAL_ERROR();
        }
    } else {
        fclose(f);
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
    new_argc += 1; /* /bin/ls */
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

    return execv("/usr/bin/sudo", new_argv);

    printf("[!] Error calling execv\n");
    FATAL_ERROR();
}
