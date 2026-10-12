from pathlib import Path
import importlib.util, subprocess, sys
p=Path(__file__).parent/'FarmCraft_50_Full_Rehearsal'/'reset_old_round_and_qa.py'
s=importlib.util.spec_from_file_location('safe_reset',p)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
assert len(m.QA)==20 and m.PROTECTED not in m.QA
assert set(m.QA)=={'QA26_B2C9C5_'+str(n).zfill(2) for n in range(1,21)}
a={'foo':[1,2],'bar':'z'}
assert m.digest(a)==m.digest({'bar':'z','foo':[1,2]})
import os
env=os.environ.copy();env.pop('DATABASE_URL',None)
r=subprocess.run([sys.executable,str(p)],env=env,capture_output=True,text=True)
assert r.returncode==2 and 'DATABASE_URL' in r.stderr
print('Reset safety checks passed: target scope, hash stability and missing-URL refusal')
