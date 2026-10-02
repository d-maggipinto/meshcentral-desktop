# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CYVELION LTD. Unofficial MeshCentral desktop client, see NOTICE.
"""Windows build metadata: build/version_info.txt (PyInstaller version resource of the .exe) and
build/LICENSE.rtf (licence page of the MSI). Usage: python make_meta.py <X.Y.Z>"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BUILD = os.path.join(ROOT, "build")

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=(%(t)s), prodvers=(%(t)s), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080904B0', [
      StringStruct('CompanyName', 'CYVELION LTD'),
      StringStruct('FileDescription', 'MeshCentral Desktop'),
      StringStruct('FileVersion', '%(v)s'),
      StringStruct('InternalName', 'MeshCentralDesktop'),
      StringStruct('LegalCopyright', 'Copyright 2026 CYVELION LTD. Apache License 2.0'),
      StringStruct('OriginalFilename', 'MeshCentralDesktop.exe'),
      StringStruct('ProductName', 'MeshCentral Desktop'),
      StringStruct('ProductVersion', '%(v)s')])]),
    VarFileInfo([VarStruct('Translation', [2057, 1200])])
  ]
)
"""


def rtf(text):
    out = []
    for ch in text:
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\par\n")
        elif ord(ch) > 127:
            out.append("\\u%d?" % (ord(ch) if ord(ch) < 32768 else ord(ch) - 65536))
        else:
            out.append(ch)
    return "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Segoe UI;}}\\f0\\fs18\n" + "".join(out) + "}\n"


def main(version):
    parts = [int(p) for p in version.split(".")] + [0] * 4
    os.makedirs(BUILD, exist_ok=True)
    with open(os.path.join(BUILD, "version_info.txt"), "w", encoding="utf-8") as f:
        f.write(VERSION_INFO % {"t": ", ".join(str(p) for p in parts[:4]), "v": version})
    with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as f:
        text = f.read()
    with open(os.path.join(BUILD, "LICENSE.rtf"), "w", encoding="ascii") as f:
        f.write(rtf(text))
    print("wrote build/version_info.txt and build/LICENSE.rtf for", version)


if __name__ == "__main__":
    main(sys.argv[1])
