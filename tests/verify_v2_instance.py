"""Retained two-process QLocalSocket wake check; never touches player profiles."""
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QCoreApplication,QTimer
from release_support import SingleInstance
work=Path(sys.argv[1]).resolve()
if not work.is_relative_to((ROOT/"tests/artifacts").resolve()):raise SystemExit("sandbox required")
if len(sys.argv)>2:
    app=QCoreApplication([]);guard=SingleInstance(work/"save_data.json")
    primary=guard.acquire()
    if sys.argv[2]=="owner":
        if not primary:raise SystemExit(2)
        count=[0];guard.awakened.connect(lambda:count.__setitem__(0,count[0]+1))
        (work/"ready").write_text(guard.name)
        QTimer.singleShot(3500,app.quit);app.exec();guard.close()
        (work/"count.json").write_text(json.dumps(count))
    else:
        if primary:guard.close();raise SystemExit(3)
        print("SECONDARY_OK")
else:
    work.mkdir(parents=True,exist_ok=False)
    owner=subprocess.Popen([sys.executable,"-B",__file__,str(work),"owner"],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    deadline=time.monotonic()+10
    while not (work/"ready").exists() and time.monotonic()<deadline:
        if owner.poll() is not None:raise SystemExit(owner.communicate()[1].decode())
        time.sleep(.05)
    for i in range(2):
        client=subprocess.run([sys.executable,"-B",__file__,str(work),"client"],cwd=ROOT,capture_output=True,timeout=5)
        if client.returncode:raise SystemExit(client.stderr.decode())
    out,err=owner.communicate(timeout=10)
    if owner.returncode or json.loads((work/"count.json").read_text())!=[2]:raise SystemExit(str((out,err)))
    print("IPC_OK: one owner, two wake messages")
