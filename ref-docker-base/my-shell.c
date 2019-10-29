#include <stdlib.h>
#include <unistd.h>
#include <stdio.h>

/*
This is a custom shell that calls /bin/bash with the -p flag.
This flag prevents bash from dropping privileges in case euid != uid.
*/

int main(int argc, char *argv[])
{
    //+1 for -p and +1 for NULL
    int new_argc = argc + 2;

    if (argc == 0)
        new_argc++;

    char *new_argv[new_argc];
    new_argv[0] = "/bin/bash";
    new_argv[1] = "-p";
    new_argv[new_argc-1] = NULL;

    if (argc > 1) {
        for (int i = 0; i < argc-1; i++) {
            new_argv[i+2] = argv[i+1];
        }
    }

    return execv("/bin/bash", new_argv);
}
