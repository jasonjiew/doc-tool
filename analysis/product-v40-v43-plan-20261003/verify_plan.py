import json,sys,pathlib,re,subprocess
root=pathlib.Path('D:/ai_develop_project_space/doc-tool')
data=json.load(sys.stdin)
outdir=root/'analysis/product-v40-v43-plan-20261003'
outdir.mkdir(parents=True,exist_ok=True)
target=outdir/'verification.json'
target.write_text('{"status":"verifying"}\n',encoding='utf-8')
errors=[]; changes=[]; paths=[root/p for p in data['documents']]
for item in data['changes']:
 name=item['name']; base=root/'openspec/changes'/name
 task=(base/'tasks.md').read_text(encoding='utf-8')
 rows=re.findall(r'^- \[([ xX])\] (\d+\.\d+) (.+)$',task,re.M)
 if [r[1] for r in rows]!=[f'{i}.{j}' for i in range(1,6) for j in range(1,5)]: errors.append(name+': invalid tasks')
 if any(r[0]!=' ' for r in rows): errors.append(name+': planned task checked')
 caps=sorted(p.name for p in (base/'specs').iterdir() if p.is_dir())
 declared=sorted(re.findall(r'^- `([^`]+)`:',(base/'proposal.md').read_text(encoding='utf-8'),re.M))
 if declared!=caps or len(caps)!=2: errors.append(name+': capability mismatch')
 md=sorted(base.rglob('*.md')); paths+=md
 if len(md)!=5 or not (base/'.openspec.yaml').is_file(): errors.append(name+': artifacts missing')
 if not item['status'].get('isComplete') or any(a['status']!='done' for a in item['status']['artifacts']): errors.append(name+': status incomplete')
 if not all(x['valid'] for x in item['strict']['items']): errors.append(name+': strict invalid')
 apply=item['apply']
 if apply.get('state')!='ready' or apply.get('progress')!={'total':20,'complete':0,'remaining':20}: errors.append(name+': apply not ready')
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
g=subprocess.run(['git','diff','--check','--']+data['documents']+['openspec/changes/'+x['name'] for x in data['changes']],cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace')
if g.returncode: errors.append('git diff --check failed')
head=subprocess.run(['git','rev-parse','--short','HEAD'],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
result={'status':'pass' if not errors else 'fail','date':data['date'],'head':head,'planningOnly':True,'businessTestsRun':False,'wordProbeOrRefreshRun':False,'newBusinessImplementation':False,'newQueue':{'batches':20,'tasks':sum(x['taskCount'] for x in changes),'checked':sum(x['checked'] for x in changes),'nextTask':'40-A 1.1'},'changes':changes,'priorTaskSnapshot':{'total':sum(x['total'] for x in old),'checked':sum(x['checked'] for x in old),'changes':old},'historicalRegressionReport':reg,'localMarkdownLinks':{'filesChecked':len(paths),'linksChecked':link_count,'broken':broken},'whitespace':{'allListedMarkdownChecked':True,'scopedGitDiffCheckExit':g.returncode,'output':g.stdout+g.stderr},'errors':errors}
target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':result['status'],'newQueue':result['newQueue'],'prior':result['priorTaskSnapshot'],'markdownFiles':len(paths),'linksChecked':link_count,'broken':broken,'errors':errors,'artifact':str(target)},ensure_ascii=False))
sys.exit(1 if errors else 0)
