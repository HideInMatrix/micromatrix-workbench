#!/usr/bin/env python3

import sys

if len(sys.argv) > 1 and sys.argv[1] == "--host-worker":
    from agent_workbench.runtime.host_worker import cli_main as host_worker_main

    raise SystemExit(host_worker_main(sys.argv[2:]))

from agent_workbench.desktop import main


if __name__ == "__main__":
    raise SystemExit(main())
