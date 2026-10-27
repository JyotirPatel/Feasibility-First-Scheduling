# Parikshit / report

**Owner:** Parikshit. **Hands to:** Riya, who assembles the final report.

This folder holds Parikshit's part of the report and presentation (Parikshit/README.md, "Report / Presentation Section"):

- `simulator_section.md` is the simulator and workload section. It explains why the simulated numbers are realistic and how the traces were generated.
- `references.bib` holds its citations.

**Where its numbers come from:**
- `../simulator/NUMBERS.md` gives the source of every number.
- `python3 simulator/calibration.py` prints the fitted constants.
- `python3 simulator/scenario_effects.py` prints the scenario table (least-load baseline, seed 0).

Re-run both after any change to `../configs/` or `../event_traces/`, and update the section.
