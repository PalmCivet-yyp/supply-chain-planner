"""Auditable advanced optimization dispatcher; no embedded benchmark answers."""
import hashlib
import json
import warnings
from pathlib import Path
from .optimization_common import atomic_json
from .optimization_checks import check

def run(kind,input_path,out,seconds=60,seed=17):
    from . import facility,routing,production,multiechelon
    path=Path(out)
    if path.exists():raise ValueError('Output directory already exists')
    raw=Path(input_path).read_bytes();data=json.loads(raw)
    path.mkdir(parents=True)
    def checkpoint(result):atomic_json(path/'checkpoint.json',result)
    funcs={'facility':facility.solve,'routing':routing.solve,'blending':production.blending,'production':production.factory,'serial':multiechelon.solve}
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore',message='Unrecognized options detected')
            result=funcs[kind](data,seconds,seed,checkpoint)
        result['validation']=check(kind,data,result)
        if result['objective'] is not None and not result['validation']['passed']:raise ValueError('Returned decision failed independent checks')
        from . import VERSION
        result.update({'engine_version':VERSION,'kind':kind,'input_sha256':hashlib.sha256(raw).hexdigest(),'parameters':{'seconds':seconds,'seed':seed,'threads':1}})
        atomic_json(path/'report.json',result)
        from .optimization_delivery import write_html
        write_html(result,path/'report.html',data)
        return result
    except Exception as error:
        atomic_json(path/'failure.json',{'status':'failed','error':str(error),'checkpoint_retained':(path/'checkpoint.json').exists(),'input_sha256':hashlib.sha256(raw).hexdigest()})
        raise
