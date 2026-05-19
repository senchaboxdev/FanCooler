/*
 * launcher.c — FanCooler.app native binary launcher
 *
 * • Detects project path relative to FanCooler.app (no hardcoded paths)
 * • Tries common Python locations; falls back to PATH
 * • Passes argv[0] = this binary so NSBundle finds FanCooler.app
 *   → single Dock icon, no Python icon
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
    /* argv[0] = /some/path/FanCooler.app/Contents/MacOS/FanCooler
       Walk up 3 levels → directory containing FanCooler.app */
    char d1[4096], d2[4096], d3[4096], parent[4096];
    safe_dirname(argv[0], d1, sizeof(d1));   /* .../Contents/MacOS */
    safe_dirname(d1, d2, sizeof(d2));         /* .../Contents       */
    safe_dirname(d2, d3, sizeof(d3));         /* .../FanCooler.app  */
    safe_dirname(d3, parent, sizeof(parent)); /* .../Desktop        */

    char script[4096];
    snprintf(script, sizeof(script), "%s/FanCooler/dashboard.py", parent);

    if (access(script, R_OK) != 0) {
        fprintf(stderr,
            "FanCooler: dashboard.py not found at %s\n"
            "Keep FanCooler/ folder next to FanCooler.app\n", script);
        return 1;
    }

    /* Try framework Pythons first (best Dock integration on macOS),
       then Homebrew Intel/ARM, then system. */
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

    fprintf(stderr, "FanCooler: Python 3 not found. "
                    "Install from python.org or brew install python3\n");
    return 1;
}
