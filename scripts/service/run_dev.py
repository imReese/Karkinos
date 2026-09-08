"""Keep the development checkout identifiable in the process command."""

import sys
from pathlib import Path

# A file entrypoint remains visible when macOS rewrites the interpreter path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
