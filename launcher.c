/*
 * launcher.c — FanCooler.app self-contained launcher (universal binary)
 *
 * Python files live inside the bundle at Contents/Resources/.
 * No external source folder needed — just copy FanCooler.app.
 *
 * Compiled as universal binary: runs on Intel AND Apple Silicon (M1/M2/M3/M4).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <libgen.h>

static void safe_dirname(const char *path, char *out, size_t sz) {
    char tmp[4096];
    strncpy(tmp, path, sizeof(tmp) - 1);
    strncpy(out, dirname(tmp), sz - 1);
}

int main(int argc, char *argv[]) {
    /* argv[0] = .../FanCooler.app/Contents/MacOS/FanCooler */
    char macos[4096], contents[4096], resources[4096], script[4096];
    safe_dirname(argv[0], macos,    sizeof(macos));       /* .../Contents/MacOS */
    safe_dirname(macos,   contents, sizeof(contents));    /* .../Contents       */
    snprintf(resources, sizeof(resources), "%s/Resources", contents);
    snprintf(script,    sizeof(script),    "%s/dashboard.py", resources);

    if (access(script, R_OK) != 0) {
        fprintf(stderr, "FanCooler: cannot find %s\n", script);
        return 1;
    }

    /* cd into Resources so 'import monitor' works without PYTHONPATH tricks */
    chdir(resources);

    /* Try framework Pythons first (best Dock/Tk integration on macOS),
       then Homebrew ARM (M-series), Homebrew Intel, system. */
    const char *candidates[] = {
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12",
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11",
        "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10",
        "/Library/Frameworks/Python.framework/Versions/3.9/bin/python3.9",
        "/Library/Frameworks/Python.framework/Versions/3.8/bin/python3.8",
        "/Library/Frameworks/Python.framework/Versions/3.6/bin/python3.6",
        "/opt/homebrew/bin/python3",   /* Homebrew Apple Silicon */
        "/usr/local/bin/python3",      /* Homebrew Intel         */
        "/usr/bin/python3",            /* System                 */
        NULL
    };

    for (int i = 0; candidates[i]; i++) {
        if (access(candidates[i], X_OK) == 0) {
            char *new_argv[] = { argv[0], script, NULL };
            execv(candidates[i], new_argv);
        }
    }

    char *path_argv[] = { (char *)"python3", script, NULL };
    execvp("python3", path_argv);

    fprintf(stderr, "FanCooler: Python 3 not found.\n"
                    "Install: https://python.org  or  brew install python3\n");
    return 1;
}
