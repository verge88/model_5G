"""Background entry point with durable logs; no additional scheduler."""
import sys
from pathlib import Path
state=Path(__file__).resolve().parents[1]/'results/ml-v1'
state.mkdir(exist_ok=True)
sys.stdout=(state/'controller.stdout.log').open('a',buffering=1,encoding='utf-8')
sys.stderr=(state/'controller.stderr.log').open('a',buffering=1,encoding='utf-8')
from ml_stage import main
main()
