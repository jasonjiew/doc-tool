import json,sys,pathlib,datetime
root=pathlib.Path('D:/ai_develop_project_space/doc-tool')
ops=json.load(sys.stdin); pending=[]
for op in ops:
 p=root/op['path']; original=p.read_text(encoding='utf-8'); new=original
 for r in op.get('replacements',[]):
  if r.get('optional'): new=new.replace(r['old'],r['replacement'])
  else:
   if new.count(r['old'])!=1: raise RuntimeError('replacement mismatch: '+op['path'])
   new=new.replace(r['old'],r['replacement'],1)
 if op.get('append'): new=new.rstrip()+'\n'+op['append']
 if 'replaceEntire' in op: new=op['replaceEntire']
 pending.append((p,original,new.rstrip()+'\n'))
backup=root/'tmp/mainline-plan-review-backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
for p,original,new in pending:
 if p.read_text(encoding='utf-8')!=original: raise RuntimeError('concurrent modification: '+str(p))
 dst=backup/p.relative_to(root); dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(p.read_bytes())
for p,original,new in pending:
 if p.read_text(encoding='utf-8')!=original: raise RuntimeError('concurrent modification before write')
 p.write_text(new,encoding='utf-8')
 if p.read_text(encoding='utf-8')!=new: raise RuntimeError('write failed')
print(json.dumps({'updated':len(pending),'backup':str(backup)},ensure_ascii=False))
