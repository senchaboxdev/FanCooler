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

    char *child_argv[] = { (char *)python, script, NULL };

    /* Fork: child becomes Python, parent exits immediately.
       Parent exit removes FanCooler.app Dock entry.
       Child (Python) is the only remaining process → one Dock icon. */
    if (fork() == 0) {
        execv(python, child_argv);
    }
    return 0;
}
