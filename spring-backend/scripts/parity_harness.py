#!/usr/bin/env python3
"""
Parity harness for migration gates.

Modes:
1) Spring-only contract gate
2) Python vs Spring parity gate (optional)
Usage:
  python3 scripts/parity_harness.py --spring http://127.0.0.1:8080 --steps 30
  python3 scripts/parity_harness.py --py http://127.0.0.1:8000 --spring http://127.0.0.1:8080 --steps 30
"""

import argparse
import json
import urllib.request


def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())


def post(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def summarize_status(s):
    return {
        "time": s.get("time"),
        "is_paused": s.get("is_paused"),
        "is_done": s.get("is_done"),
        "active": len(s.get("active_lots", [])),
        "processing": (s.get("kpi") or {}).get("processing_lots"),
        "finished": (s.get("kpi") or {}).get("finished_lots"),
        "progress_signature": s.get("progress_signature"),
    }


def validate_contract(s):
    required = [
        "status_seq",
        "time",
        "is_paused",
        "is_done",
        "target_machine",
        "queue",
        "active_lots",
        "progress_signature",
        "kpi",
    ]
    return [k for k in required if k not in s]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--py", default=None)
    p.add_argument("--spring", default="http://127.0.0.1:8080")
    p.add_argument("--steps", type=int, default=20)
    args = p.parse_args()

    post(f"{args.spring}/api/control/reset")
    post(f"{args.spring}/api/control/resume")

    contract_errors = []
    mismatches = []
    for i in range(args.steps):
        sp_s = post(f"{args.spring}/api/step")
        missing = validate_contract(sp_s)
        if missing:
            contract_errors.append({"step": i + 1, "missing_keys": missing})

        if args.py:
            py_s = post(f"{args.py}/api/step")
            a = summarize_status(py_s)
            b = summarize_status(sp_s)
            if a != b:
                mismatches.append({"step": i + 1, "python": a, "spring": b})

    report = {
        "steps": args.steps,
        "contract_error_count": len(contract_errors),
        "contract_errors": contract_errors[:10],
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:10],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
