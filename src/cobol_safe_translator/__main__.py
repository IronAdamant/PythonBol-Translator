"""Allow running the package as ``python -m cobol_safe_translator``.

Usage:
    python -m cobol_safe_translator --mcp          # start MCP server
    python -m cobol_safe_translator translate ...   # normal CLI
"""

import sys

if "--mcp" in sys.argv:
    from .mcp_server import main
    main()
else:
    from .cli import main
    sys.exit(main())
