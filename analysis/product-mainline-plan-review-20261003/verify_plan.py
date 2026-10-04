import json,sys,pathlib,re,subprocess
root=pathlib.Path('D:/ai_develop_project_space/doc-tool')
data=json.load(sys.stdin)
outdir=root/'analysis/product-mainline-plan-review-20261003'
outdir.mkdir(parents=True,exist_ok=True)
target=outdir/'verification.json'
target.write_text('{"status":"verifying"}\n',encoding='utf-8')
errors=[]; changes=[]; paths=[root/p for p in data['documents']]
for item in data['changes']:
 name=item['name']; base=root/'openspec/changes'/name
 groups=6 if name=='product-mainline-usability-and-fidelity' else 5
 cap_count=4 if groups==6 else 2
 expected_tasks=groups*4
 task=(base/'tasks.md').read_text(encoding='utf-8')
 rows=re.findall(r'^- \[([ xX])\] (\d+\.\d+) (.+)$',task,re.M)
 if [r[1] for r in rows]!=[f'{i}.{j}' for i in range(1,groups+1) for j in range(1,5)]: errors.append(name+': invalid tasks')
 if any(r[0]!=' ' for r in rows): errors.append(name+': planned task checked')
 caps=sorted(p.name for p in (base/'specs').iterdir() if p.is_dir())
 declared=sorted(re.findall(r'^- `([^`]+)`:',(base/'proposal.md').read_text(encoding='utf-8'),re.M))
 if declared!=caps or len(caps)!=cap_count: errors.append(name+': capability mismatch')
 md=sorted(base.rglob('*.md')); paths+=md
 if len(md)!=3+cap_count or not (base/'.openspec.yaml').is_file(): errors.append(name+': artifacts missing')
 if not item['status'].get('isComplete') or any(a['status']!='done' for a in item['status']['artifacts']): errors.append(name+': status incomplete')
 if not all(x['valid'] for x in item['strict']['items']): errors.append(name+': strict invalid')
 apply=item['apply']
 if apply.get('state')!='ready' or apply.get('progress')!={'total':expected_tasks,'complete':0,'remaining':expected_tasks}: errors.append(name+': apply not ready')
 (outdir/(name+'-cli.json')).write_text(json.dumps(item,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 reqs=sum(len(re.findall(r'^### Requirement:',p.read_text(encoding='utf-8'),re.M)) for p in md if p.name=='spec.md')
 scenarios=sum(len(re.findall(r'^#### Scenario:',p.read_text(encoding='utf-8'),re.M)) for p in md if p.name=='spec.md')
 changes.append({'name':name,'planningArtifacts':'4/4','strictValid':True,'applyState':apply['state'],'taskCount':len(rows),'checked':sum(r[0]!=' ' for r in rows),'capabilities':caps,'requirements':reqs,'scenarios':scenarios})
paths=list(dict.fromkeys(paths)); link_count=0; broken=[]
for p in paths:
 txt=p.read_text(encoding='utf-8')
 for i,line in enumerate(txt.splitlines(),1):
  if line.rstrip()!=line: errors.append(str(p.relative_to(root))+': trailing whitespace:'+str(i))
 for raw in re.findall(r'!?\[[^\]\n]+\]\(([^)\n]+)\)',txt):
  ref=raw.strip().strip('<>')
  if re.match(r'^[a-zA-Z]+://',ref) or ref.startswith('#'): continue
  ref=ref.split('#',1)[0].split('?',1)[0]
  link_count+=1
  if not (p.parent/ref).resolve().exists(): broken.append({'document':str(p.relative_to(root)).replace('\\','/'),'target':raw})
if broken: errors.append('broken local markdown links')
old=[]
for name in ['product-main-workflow-optimization','product-v37-daily-workflow-ux','product-v38-authoring-and-exchange-ux','product-v39-rd-workspace-productivity']:
 rows=re.findall(r'^- \[([ xX])\]',(root/'openspec/changes'/name/'tasks.md').read_text(encoding='utf-8'),re.M)
 old.append({'name':name,'total':len(rows),'checked':sum(x.lower()=='x' for x in rows)})
report=json.loads((root/'analysis/regression/report.json').read_text(encoding='utf-8'))
reg={'origin':'analysis/regression/report.json','readOnly':True,'files':len(report['files']),'totals':report['totals'],'nonzeroFiles':report['failedFiles'],'timedOutFiles':report['timedOutFiles']}
prompt=(root/'docs/product-v40-v43-execution-prompt.md').read_text(encoding='utf-8')
queue=re.findall(r'^\d+\. (product-[a-z0-9-]+)',prompt,re.M)
expected_queue=[i['name'] for i in data['changes']]
if queue!=expected_queue: errors.append('canonical prompt queue differs from planning order')
for doc in ['product-v40-v43-roadmap.md','product-v40-v43-execution.md','product-v40-v43-execution-prompt.md','product-mainline-optimization.md','product-execution-confirmed-prompt.md','product-next-execution.md']:
 text=(root/'docs'/doc).read_text(encoding='utf-8')
 if '104' not in text or '26' not in text or 'MAIN2' not in text: errors.append(doc+': missing new queue scope')
 if re.search(r'0/80|四包26|4 个 change、8',text): errors.append(doc+': stale active scope')
ledger=(root/'docs/product-v40-v43-execution.md').read_text(encoding='utf-8')
for name in expected_queue:
 if name not in ledger: errors.append('ledger missing '+name)
if sum(c['taskCount'] for c in changes)!=104: errors.append('new task count not 104')
if sum(len(c['capabilities']) for c in changes)!=12: errors.append('new capability count not 12')
g=subprocess.run(['git','diff','--check','--']+data['documents']+['openspec/changes/'+x['name'] for x in data['changes']],cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace')
if g.returncode: errors.append('git diff --check failed')
head=subprocess.run(['git','rev-parse','--short','HEAD'],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
result={'status':'pass' if not errors else 'fail','date':data['date'],'head':head,'planningOnly':True,'businessTestsRun':False,'wordProbeOrRefreshRun':False,'newBusinessImplementation':False,'canonicalPromptQueue':queue,'newQueue':{'batches':26,'tasks':sum(x['taskCount'] for x in changes),'checked':sum(x['checked'] for x in changes),'nextTask':'40-A 1.1'},'changes':changes,'priorTaskSnapshot':{'total':sum(x['total'] for x in old),'checked':sum(x['checked'] for x in old),'changes':old},'historicalRegressionReport':reg,'localMarkdownLinks':{'filesChecked':len(paths),'linksChecked':link_count,'broken':broken},'whitespace':{'allListedMarkdownChecked':True,'scopedGitDiffCheckExit':g.returncode,'output':g.stdout+g.stderr},'errors':errors}
target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':result['status'],'newQueue':result['newQueue'],'prior':result['priorTaskSnapshot'],'markdownFiles':len(paths),'linksChecked':link_count,'broken':broken,'errors':errors,'artifact':str(target)},ensure_ascii=False))
sys.exit(1 if errors else 0)
