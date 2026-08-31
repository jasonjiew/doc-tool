# Runtime bootstrap hook: make the standard import machinery find extension
# modules that were renamed from *.pyd to *.dll at packaging time.
#
# Why: on machines running a transparent-encryption client (EsafeNet DocGuard
# and similar), *.pyd files are stored encrypted at rest and DocTool.exe is
# not in the client's trusted-process list, so loading any *.pyd from the
# install directory fails with ERROR_BAD_EXE_FORMAT ("%1 is not a valid Win32
# application"). The encryption policy does not cover *.dll, so packaging
# rewrites every *.pyd to *.dll (plaintext at rest). This hook teaches the
# path-based import system to treat *.dll as an extension-module suffix.
#
# Note: on CPython 3.13 the FileFinder path hook is registered at interpreter
# startup with the suffix list returned by _imp.extension_suffixes(); mutating
# importlib.machinery.EXTENSION_SUFFIXES afterwards has no effect. The hook in
# sys.path_hooks must be replaced and the importer cache cleared.

import importlib.machinery
import importlib._bootstrap_external as _be
import sys

_suffixes = list(importlib.machinery.EXTENSION_SUFFIXES)
if ".dll" not in _suffixes:
    _suffixes.append(".dll")

_loaders = [
    (importlib.machinery.ExtensionFileLoader, _suffixes),
    (importlib.machinery.SourceFileLoader, importlib.machinery.SOURCE_SUFFIXES),
    (importlib.machinery.SourcelessFileLoader, importlib.machinery.BYTECODE_SUFFIXES),
]

_new_hook = _be.FileFinder.path_hook(*_loaders)
for _i, _existing in enumerate(sys.path_hooks):
    if getattr(_existing, "__name__", "") == "path_hook_for_FileFinder":
        sys.path_hooks[_i] = _new_hook
        break
else:
    sys.path_hooks.append(_new_hook)

sys.path_importer_cache.clear()
