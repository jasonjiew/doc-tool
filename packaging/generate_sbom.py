# -*- coding: utf-8 -*-
"""从锁定 requirements 生成 CycloneDX 1.5 JSON 与 SPDX 2.3 JSON。"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


def dependencies(paths):
    found = {}
    for path in paths:
        for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s#]+)", line)
            if match:
                found[match.group(1).lower()] = (match.group(1), match.group(2), Path(path).name)
    return [found[key] for key in sorted(found)]


def generate(requirements, cyclone_path, spdx_path):
    deps = dependencies(requirements)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cyclone = {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": "urn:uuid:{0}".format(uuid.uuid4()),
        "version": 1, "metadata": {"timestamp": timestamp, "component": {"type": "application", "name": "KonsungDocTool"}},
        "components": [
            {"type": "library", "name": name, "version": version, "purl": "pkg:pypi/{0}@{1}".format(name.lower(), version), "properties": [{"name": "scopeFile", "value": source}]}
            for name, version, source in deps
        ],
    }
    spdx = {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
        "name": "KonsungDocTool-SBOM", "documentNamespace": "https://konsung.example/sbom/{0}".format(timestamp.replace(":", "-")),
        "creationInfo": {"created": timestamp, "creators": ["Tool: doc-tool-generate-sbom"]},
        "packages": [
            {"name": name, "SPDXID": "SPDXRef-Package-{0}".format(re.sub(r"[^A-Za-z0-9.-]", "-", name)), "versionInfo": version,
             "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
             "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": "pkg:pypi/{0}@{1}".format(name.lower(), version)}]}
            for name, version, _source in deps
        ],
    }
    Path(cyclone_path).parent.mkdir(parents=True, exist_ok=True)
    Path(cyclone_path).write_text(json.dumps(cyclone, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(spdx_path).write_text(json.dumps(spdx, ensure_ascii=False, indent=2), encoding="utf-8")
    return cyclone, spdx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", action="append", required=True)
    parser.add_argument("--cyclonedx", required=True)
    parser.add_argument("--spdx", required=True)
    args = parser.parse_args()
    generate(args.requirements, args.cyclonedx, args.spdx)


if __name__ == "__main__":
    main()
