# core

A room kept ready: this is where Zygote's own programs will live inside a project, so the project carries the tools that build it (the garage inside
the car). Today the program is still run from the installed Zygote, and `Run project.exe` reaches it by the one absolute path it was compiled with.

**File > Update project's core** copies the installed Zygote's `app` folder and its version into `.zygote\core` of the open project, after one short question
("Update <project> from X to Y?"; when everything already matches a toast says so and nothing is asked). Dropping a project folder on an open Zygote offers the same. Opening a project by itself never changes this folder.

Nothing reads from here yet. When that changes, this note and the launcher change with it.
