#include <stdlib.h>
#include <unistd.h>
#include <stdio.h>

int main(int argc, char *argv[]) {
    const char *home = getenv("HOME");
    if (!home) return 1;

    /* dashboard.py path */
    char script[1024];
    snprintf(script, sizeof(script),
             "%s/Desktop/FanCooler/dashboard.py", home);

    const char *python =
        "/Library/Frameworks/Python.framework"
        "/Versions/3.6/bin/python3.6";

    /*
     * Pass argv[0] = THIS binary (inside FanCooler.app).
     * Python / NSBundle.mainBundle() walks up argv[0] to find
     * the enclosing .app bundle → finds FanCooler.app → one Dock icon.
     */
    char *new_argv[] = { argv[0], script, NULL };
    execv(python, new_argv);

    perror("fancooler: exec failed");
    return 1;
}
