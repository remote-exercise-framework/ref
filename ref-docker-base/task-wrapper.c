#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <assert.h>

extern char **environ;
const char *env_dump_path = "/tmp/.user_environ";

#define FATAL_ERROR() printf("[!] If the problem persist, please contact your system administrator.\n");

int main(int argc, char const *argv[])
{
    char **env = environ;
    FILE *f;

    /* Open the file we are going to dump the users environ into */
    f = fopen(env_dump_path, "w");
    if (!f) {
        printf("[!] Error while dumping environment\n");
        FATAL_ERROR();
        exit(1);
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
            exit(1);
        }

        env++;
    }
    fclose(f);


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
    exit(1);
}
