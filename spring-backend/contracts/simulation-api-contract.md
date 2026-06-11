# Simulation API Contract (Frozen for Spring Facade)

This contract is frozen from the current Python backend (`SMT_2000_Simulation/main_api.py`) and frontend usage (`fab-dashboard/src/App.vue`).

## Endpoints

- `GET /`
  - response: `{ "status": string, "simulation_time": number }`
- `GET /api/status`
  - response: `StatusResponse`
- `POST /api/step`
  - response: `StatusResponse`
- `POST /api/control/reset`
  - response: `StatusResponse`
- `POST /api/control/pause`
  - response: `StatusResponse`
- `POST /api/control/resume`
  - response: `StatusResponse`
- `POST /api/dispatch`
  - request: `{ "action_idx": number }`
  - response: `StatusResponse`
- `GET /api/layout`
  - response: `{ [group: string]: MachineLayoutItem[] }`
- `POST /api/debug/ui-event`
  - request: `{ "event": string, "details": object }`
  - response: `{ "ok": true }`
- `GET /api/debug/file-write-check`
  - response: `{ "ok": boolean, "path"?: string, "error"?: string }`

## StatusResponse Schema

```json
{
  "status_seq": 0,
  "time": 0.0,
  "is_paused": true,
  "is_done": false,
  "target_machine": null,
  "queue": [
    {
      "index": 0,
      "lot_name": "Lot_Product_3_1",
      "product": "3",
      "priority": 10,
      "rem_steps": 583,
      "due_date": "1000.0",
      "q_danger": "0.00"
    }
  ],
  "active_lots": [
    {
      "lot_name": "Lot_Product_3_1",
      "product": "Route_Product_E3",
      "rem_steps": 583,
      "total_steps": 583,
      "due_date": "1000.0",
      "status": "Queuing"
    }
  ],
  "progress_signature": "Lot_Product_3_1:583:Queuing",
  "kpi": {
    "finished_lots": 0,
    "avg_tat": 0.0,
    "q_viol": 0,
    "processing_lots": 0
  }
}
```

## Non-obvious rules to keep

- `due_date` and `q_danger` are formatted strings in queue payload.
- `target_machine` can be `null` while `active_lots` exists.
- `status_seq` increases per status snapshot.
- Frontend expects snake_case JSON keys exactly as above.
