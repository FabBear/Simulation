"""
Lightweight KPI regression runner.

Usage:
  python tests/kpi_regression_runner.py
"""

from backend_manager import SimulationManager


def run_steps(steps=200):
    manager = SimulationManager()
    manager.toggle_pause(False)
    last = None
    for _ in range(steps):
        last = manager.proceed_step()
        if last.get("is_done"):
            break
    return last


if __name__ == "__main__":
    status = run_steps(steps=300)
    print("time:", status.get("time"))
    print("finished_lots:", status.get("kpi", {}).get("finished_lots"))
    print("avg_tat:", status.get("kpi", {}).get("avg_tat"))
    print("q_viol:", status.get("kpi", {}).get("q_viol"))
