# DISPATCHING / Superhot 우선순위

Toolgroup `DISPATCHING` 컬럼과 queue dispatch 우선순위.

## 우선순위 (높음 → 낮음)

1. **Superhotlot** (P4): queue에 `super_hot` lot이 있으면 그 중에서만 선택 (RUN 중 선점 없음)
2. **Toolgroup Ranking 1/2/3** (`Highest Lotpriority`, `Least Setuptime`, `Critical Ratio`)
3. **기본**: superhot → priority → least setup → CR

## Setupavoidance

- `DISPATCHING`에 `Setupavoidance` 포함 시 `min_run_length` 제약 적용 (셋업 변경 전 의무 run 수)
- `Setups` 테이블 `MINMAL NUMBER OF RUNS`와 연동

## TOOL WAKE UP Ranking

장비 **선택** (`_choose_tool_for_lot`)에만 적용. Queue 내 lot 순서와 별개.

- `Least Setuptime`, `Shortest Queue`, `Idle First` (문자열 부분 일치)
