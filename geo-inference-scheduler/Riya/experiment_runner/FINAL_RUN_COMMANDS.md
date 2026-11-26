# Run the final evaluation in Windows PowerShell

Start in `geo-inference-scheduler/Riya`, with your virtual environment active.

```powershell
python -m pip install -r experiment_runner/requirements.txt
python -m pytest tests -q
python -X utf8 experiment_runner/run_evaluation.py --config experiment_runner/config_final_validation.json --output experiment_runner/results/final_validation --workers 4
python -X utf8 experiment_runner/run_evaluation.py --config experiment_runner/config_final.json --output experiment_runner/results/final_02 --workers 6
python -X utf8 experiment_runner/verify_results.py --results experiment_runner/results/final_02 --deep
python experiment_runner/analyze_final.py --results experiment_runner/results/final_02
python figures/plot_results.py --results experiment_runner/results/final_02
```

Choose a fresh output name if the folder exists. Resume an interrupted final command by
adding `--resume`, without changing code, data, dependencies or the config. Worker count
may change when resuming. Full config = 420 main runs + 120 missing ablation runs + 60
true-state reference runs. `analysis/main_run_coverage.json` isolates the 420-run main grid.

Keep raw Parquet logs and the input snapshot as a full reproducibility bundle. Commit the
small summaries, config, source record, verifier output and figures; store the complete
bundle in shared storage. Do not add your `.venv` or old 9 GB CSV bundle to Git.
