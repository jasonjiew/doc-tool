import sys, json
sys.path.insert(0,'.')
d = json.load(open('analysis/v42/measure-staged.json', encoding='utf-8'))
for t in d['tiers']:
    print('=== chapters', t['chapters'])
    for name, st in t['stages'].items():
        print('   {0:<22} p50={1:>8.1f} p95={2:>8.1f}'.format(name, st.get('p50Ms', -1), st.get('p95Ms', -1)))