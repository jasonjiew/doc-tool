import xml.etree.ElementTree as ET

tree = ET.parse('analysis/markdown-mermaid-preview-fidelity/full.xml')
root = tree.getroot()
print('Total stats:', root.attrib)

failed_suites = []
for suite in root.iter('testsuite'):
    f = int(suite.attrib.get('failures', 0))
    e = int(suite.attrib.get('errors', 0))
    s = int(suite.attrib.get('skipped', 0))
    t = int(suite.attrib.get('tests', 0))
    name = suite.attrib.get('name')
    if f > 0 or e > 0:
        failed_suites.append((name, t, f, e, s))
        print(f"FAILED SUITE: {name} (tests={t}, failures={f}, errors={e}, skipped={s})")
        for tc in suite.iter('testcase'):
            for fail in tc.iter('failure'):
                print(f"  FAIL: {tc.attrib.get('name')}")
                print(f"    Message: {fail.attrib.get('message', '')[:120]}")
            for err in tc.iter('error'):
                print(f"  ERR: {tc.attrib.get('name')}")
                print(f"    Message: {err.attrib.get('message', '')[:120]}")

print("\nSummary of failed suites count:", len(failed_suites))
