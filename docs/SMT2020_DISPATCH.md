# DISPATCHING / Superhot 우선순위

Toolgroup `DISPATCHING` 컬럼과 queue dispatch 우선순위.

## 우선순위 (높음 → 낮음)

1. **Superhotlot** (P4): queue에 `super_hot` lot이 있으면 그 중에서만 선택 (RUN 중 선점 없음)
2. **Toolgroup Ranking 1/2/3** (`Highest Lotpriority`, `Least Setuptime`, `FIFO` via `enqueue_time`)
3. **CR** (항상 FIFO 다음, `idx` 직전): `(due_date - now) / rem_steps` (작을수록 급함)
4. **기본** (ranking 컬럼 전부 비어 있을 때): superhot → priority → setup → FIFO → CR
5. **동점**: queue 리스트 `idx` (최후 tie-break)

## Setupavoidance

- `DISPATCHING`에 `Setupavoidance` 포함 시 `min_run_length` 제약 적용 (셋업 변경 전 의무 run 수)
- `Setups` 테이블 `MINMAL NUMBER OF RUNS`와 연동

## TOOL WAKE UP Ranking

장비 **선택** (`_choose_tool_for_lot`)에만 적용. Queue 내 lot 순서와 별개.

- Excel 문자열 **부분 일치** 시 맨 앞에 한 번 더 반영: `Shortest Queue` → `Least Setuptime` → `Idle First`
- **기본 suffix** (wakeup 비어 있어도 항상): `queue_len` → `setup_time` → `busy`(유휴 우선) → `other_prod` → `tool_id`
