#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcdesktop.app import main
if __name__ == "__main__":
    sys.exit(main())
