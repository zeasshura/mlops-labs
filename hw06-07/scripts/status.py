"""Read-only compact status from the real MLflow backend."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mlflow import MlflowClient
from src.common import load_params
p=load_params();client=MlflowClient(tracking_uri=p['tracking']['uri'])
experiment=client.get_experiment_by_name(p['tracking']['experiment'])
for run in reversed(client.search_runs([experiment.experiment_id],"tags.kind = 'candidate'",order_by=['attributes.start_time DESC'])):
    print(run.data.tags['candidate'],run.info.status,'train_step='+str(run.data.metrics.get('steps','—')),
          'last_val='+str(run.data.metrics.get('val_loss','—')),
          'trainable='+str(run.data.metrics.get('trainable_params','—')))
if Path('metrics/pipeline-status.json').exists():print(json.loads(Path('metrics/pipeline-status.json').read_text()))
