#include <stdlib.h>
#include <unistd.h>
#include <stdio.h>

int main(int argc, char *argv[]) {
    const char *home = getenv("HOME");
    if (!home) return 1;

    char script[1024];
    snprintf(script, sizeof(script),
             "%s/Desktop/FanCooler/dashboard.py", home);

    const char *python =
        "/Library/Frameworks/Python.framework"
        "/Versions/3.6/bin/python3.6";

    /* Pass argv[0] = this binary (inside FanCooler.app).
       NSBundle.mainBundle() walks up argv[0] → finds FanCooler.app
       → Dock uses FanCooler's icon from the start, no flicker.        */
    char *new_argv[] = { argv[0], script, NULL };
    execv(python, new_argv);
    return 1;
}
