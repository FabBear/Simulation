# models.py

# 1. 필요한 도구(라이브러리)들을 꺼내옵니다.
from sqlalchemy import (
    Column, String, Integer, Boolean, Float, Text, DateTime, Date,
    ForeignKey, BigInteger, UniqueConstraint, Index,
)
from datetime import datetime
from sqlalchemy import MetaData
from sqlalchemy.orm import declarative_base  # .ext.declarative 대신 .orm 사용
try:
    from sqlalchemy.dialects.postgresql import JSONB
except ImportError:
    JSONB = Text  # fallback for non-Postgres dev

from schema_config import DB_SCHEMA

# 2. 설계도 용지를 한 장 꺼냅니다. (POSTGRES_SCHEMA, default simulation)
Base = declarative_base(metadata=MetaData(schema=DB_SCHEMA or None))

# -----------------------------------------------------------
# [설계도 1] 장비(Machine) 테이블 설계도
# -----------------------------------------------------------
class ToolGroup(Base):
    __tablename__ = "toolgroup"  # DB에 'toolgroup'이라는 이름으로 표를 만듭니다.

    # 엑셀의 ToolGroup 컬럼 -> DB의 toolgroup_name 칸
    toolgroup_name = Column(String, primary_key=True) 
    num_tools = Column(Integer)
    location = Column(String)
    
    # 시뮬레이션용 스위치 (YES/NO)
    is_cascading = Column(Boolean, default=False)
    is_batching = Column(Boolean, default=False)
    
    # 배치(Batch) 관련 정보
    batch_criterion = Column(String, nullable=True)
    batch_unit = Column(String, nullable=True)
    
    # 시간 정보 (분 단위)
    loading_time = Column(Float, default=0.0)
    unloading_time = Column(Float, default=0.0)
    
    # 규칙 정보
    dispatch_rule = Column(String, nullable=True)
    ranking_1 = Column(String, nullable=True)
    ranking_2 = Column(String, nullable=True)
    ranking_3 = Column(String, nullable=True)
    tool_wakeup_ranking = Column(String, nullable=True)

# -----------------------------------------------------------
# [설계도 2] 공정 순서(Route) 테이블 설계도 (방금 질문하신 부분!)
# -----------------------------------------------------------
class ProcessStep(Base):
    __tablename__ = "process_step"

    # 복합 열쇠 (이 두 개가 합쳐져야 하나의 고유한 스텝을 찾을 수 있음)
    route_id = Column(String, primary_key=True)      # 예: Route_Product_E3
    step_seq = Column(Integer, primary_key=True)     # 예: 227
    
    step_name = Column(String)                       # 예: 259_Wet_Etch
    area = Column(String)                            # 예: Wet_Etch
    target_tool_group = Column(String)               # 어떤 장비로 가야 하는지

    # 공정 시간 계산용
    proc_unit = Column(String)                       # Wafer / Lot / Batch
    proc_time_dist = Column(String, nullable=True)                  # 분포 형태 (uniform 등)
    proc_time_mean = Column(Float)                   # 평균 시간                  
    proc_time_offset = Column(Float, nullable=True)                 # 오프셋
    proc_time_unit = Column(String)                  # 단위 (min)

    # 복잡한 로직들 (값이 없을 수도 있어서 nullable=True)
    cascading_interval = Column(Float, nullable=True)
    batch_min = Column(Integer, nullable=True)
    batch_max = Column(Integer, nullable=True)

    # 셋업 정보
    setup_id = Column(String, nullable=True)
    setup_policy = Column(String, nullable=True)
    setup_time_mean = Column(Float, nullable=True)
    setup_time_offset = Column(Float, nullable=True)

    # 제약 조건
    ltl_dedication_step = Column(Integer, nullable=True)
    rework_prob = Column(Float, nullable=True)
    rework_target_step = Column(Integer, nullable=True)
    sampling_prob = Column(Float, default=100.0)

    # CQT (Critical Queue Time) — anchor row STEP=n, target STEP FOR CRITICAL QUEUE TIME=m
    cqt_anchor_step = Column(Integer, nullable=True)
    cqt_target_step = Column(Integer, nullable=True)
    cqt_start_step = Column(Integer, nullable=True)  # legacy alias of cqt_target_step
    cqt_limit = Column(Float, nullable=True)
    cqt_unit = Column(String, nullable=True)
    
# -----------------------------------------------------------
# [설계도 3] PM(점검) 테이블 설계도
# -----------------------------------------------------------
class PMEvent(Base):
    __tablename__ = "pm_event"

    id = Column(Integer, primary_key=True, autoincrement=True) # 번호표 자동 발급
    pm_name = Column(String)
    
    target_tool_group = Column(String) # 어떤 장비 점검인지
    
    pm_type = Column(String)     # 시간 기반인지 횟수 기반인지
    mtbf = Column(Float)         # 고장 간격
    mtbf_unit = Column(String)
    
    duration_mean = Column(Float)   # 수리 시간 평균
    duration_offset = Column(Float) # 수리 시간 편차
    duration_dist = Column(String, nullable=True)
    duration_unit = Column(String)
    
    first_occurrence = Column(Float) # 첫 점검 시작 시간
    foa_dist = Column(String, nullable=True)
    foa_unit = Column(String, nullable=True)

# -----------------------------------------------------------
# [설계도 4] Breakdown(고장) 테이블 설계도 (신규 추가!)
# -----------------------------------------------------------
class BreakdownEvent(Base):
    __tablename__ = "breakdown_event"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 고장 이벤트 이름 (예: BREAK_Def_Met)
    event_name = Column(String)
    
    # 적용 범위 (이 데이터가 어디에 적용되는지)
    scope = Column(String)          # 예: area
    target_name = Column(String)    # 예: Def_Met, Litho (구역 이름)
    
    # 고장 간격 (TTF: Time To Failure) - 언제 고장나는가?
    ttf_dist = Column(String)       # 예: exponential
    mttf_mean = Column(Float)       # 예: 10080.0
    mttf_unit = Column(String)      # 예: min
    
    # 수리 시간 (TTR: Time To Repair) - 고치는 데 얼마나 걸리는가?
    ttr_dist = Column(String)       # 예: exponential
    mttr_mean = Column(Float)       # 예: 35.28
    mttr_unit = Column(String)      # 예: min
    
    # 첫 고장 발생 시점 (First One At)
    foa_dist = Column(String)       # 예: exponential
    foa_mean = Column(Float)        # 예: 10080.0
    foa_unit = Column(String)       # 예: min

# -----------------------------------------------------------
# [설계도 5] 제품 투입 정보 (Lot Release)
# -----------------------------------------------------------
class LotRelease(Base):
    __tablename__ = "lot_release"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    product_name = Column(String)    # 예: Product_3
    route_name = Column(String)      # 예: Route_Product_E3
    lot_type = Column(String)        # 예: Engineering_Lot_3_1
    
    priority = Column(Integer)       # 예: 10, 20
    is_super_hot_lot = Column(String) # 예: yes/no (Boolean 변환 고려)
    wafers_per_lot = Column(Integer) # 예: 25
    
    start_date = Column(String)      # 예: 01-01-18 ... (나중에 datetime 변환)
    due_date = Column(String)        # 납기일
    
    release_dist = Column(String)    # 예: constant
    release_interval = Column(Float) # 예: 51.69
    release_unit = Column(String)    # 예: min
    lots_per_release = Column(Integer) # 예: 1

# -----------------------------------------------------------
# [설계도 6] 셋업 시간 및 규칙 (Setups)
# -----------------------------------------------------------
class SetupInfo(Base):
    __tablename__ = "setup_info_final"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    setup_group = Column(String)     # 예: Implant_Gas
    from_setup = Column(String)      # 예: SU128_3
    to_setup = Column(String)        # 예: SU128_1
    
    setup_time = Column(Float)       # 예: 72.0
    setup_unit = Column(String)      # 예: min
    
    min_run_length = Column(Integer, nullable=True) # 예: 7 (Null 가능)

# -----------------------------------------------------------
# [설계도 7] 이동 시간 (Transport)
# -----------------------------------------------------------
class TransportTime(Base):
    __tablename__ = "transport_time"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    from_loc = Column(String)        # 예: Fab
    to_loc = Column(String)          # 예: Fab
    
    dist_type = Column(String)       # 예: uniform
    mean_time = Column(Float)        # 예: 7.5
    offset_time = Column(Float)      # 예: 2.5
    time_unit = Column(String)       # 예: min

# -----------------------------------------------------------
# [설계도 7b] 시뮬 에피소드(run) 메타 (CSV run_id / FabEnv _csv_run_id)
# -----------------------------------------------------------
class SimulationRun(Base):
    __tablename__ = "simulation_run"

    run_id = Column(String, primary_key=True)
    source_path = Column(String, nullable=True)
    imported_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    sim_end_minutes = Column(Float, nullable=True)
    note = Column(Text, nullable=True)


# -----------------------------------------------------------
# [설계도 8] 시뮬레이션 이력 로그 (Simulation Log)
# -----------------------------------------------------------
class SimulationLog(Base):
    __tablename__ = "simulation_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True, nullable=True)

    # 1. 누가? (Lot 정보)
    lot_id = Column(String)        # Lot 이름 (예: Lot_Product_3_1)
    product = Column(String)       # 제품명
    
    # 2. 어디서? (공정 정보)
    route_id = Column(String)      # 라우트 ID
    step_seq = Column(Integer)     # 스텝 번호 (100, 200...)
    step_name = Column(String)     # 스텝 이름 (Deposition, Etch...)
    tool_group = Column(String)    # 장비 그룹 (Litho_FE...)
    tool_id = Column(String, index=True, nullable=True)  # 개별 물리 장비 ID
    
    # 3. 언제/무엇을? (시간 및 상태)
    # 시뮬레이션 상의 '분(minute)' 단위 시간
    arrive_time = Column(Float)    # 대기열 도착 시간 (Queue In)
    start_time = Column(Float)     # 작업 시작 시간 (Track In / Processing Start)
    end_time = Column(Float)       # 작업 완료 시간 (Track Out / Processing End)
    
    # 4. 성적표 (파생 변수 - SQL로 계산해도 되지만 편의상 저장)
    queue_time = Column(Float)     # 대기 시간 (start - arrive)
    process_time = Column(Float)   # 공정 시간 (end - start)
    
    # 5. 기타 이벤트
    event_type = Column(String)    # 'PROCESS', 'BREAKDOWN' 등 구분

class LotEventLog(Base):
    __tablename__ = "lot_event_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True, nullable=True)
    lot_id = Column(String, index=True)
    product = Column(String)
    route_id = Column(String)
    step_seq = Column(Integer, nullable=True)
    tool_group = Column(String, nullable=True)
    tool_id = Column(String, index=True, nullable=True)
    event_type = Column(String, index=True)  # ARRIVAL/START/FINISH/TRANSPORT/SCRAP/REWORK/CQT_START/CQT_END
    event_time = Column(Float, index=True)
    detail_1 = Column(String, nullable=True)
    detail_2 = Column(String, nullable=True)


class LotReleaseLedger(Base):
    """One row per lot at fab release (FORWARD/cold-start run log)."""

    __tablename__ = "lot_release_ledger"
    __table_args__ = (
        Index("ix_lot_release_ledger_run", "run_id"),
        UniqueConstraint("run_id", "lot_id", name="uq_lot_release_ledger_run_lot"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True, nullable=True)
    scenario_id = Column(String(64), nullable=True)
    lot_id = Column(String, index=True, nullable=False)
    lot_type = Column(String, nullable=True)
    product_name = Column(String, nullable=True)
    route_name = Column(String, nullable=True)
    sim_now_min = Column(Float, nullable=False)
    due_date_sim_min = Column(Float, nullable=False)
    priority = Column(Integer, nullable=True)
    is_super_hot = Column(Boolean, nullable=False, default=False)
    wafers_per_lot = Column(Integer, nullable=True)
    source = Column(String(32), nullable=True)


class ToolStateLog(Base):
    __tablename__ = "tool_state_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True, nullable=True)
    tool_group = Column(String, index=True)
    tool_id = Column(String, index=True, nullable=True)  # 집계 로그에서는 NULL (유닛별 #k 미기록)
    state = Column(String, index=True)  # 그룹 대표: DOWN_BM > DOWN_PM > SETUP > RUN > IDLE
    state_change_time = Column(Float, index=True)
    setup_name = Column(String, nullable=True)
    lot_id = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    idle_units = Column(Integer, nullable=True)
    run_units = Column(Integer, nullable=True)
    setup_units = Column(Integer, nullable=True)
    down_pm_units = Column(Integer, nullable=True)
    down_bm_units = Column(Integer, nullable=True)

class ActiveCqtTimer(Base):
    __tablename__ = "active_cqt_timer"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lot_id = Column(String, index=True)
    start_step = Column(Integer)
    target_step = Column(Integer)
    deadline_time = Column(Float, index=True)
    started_at = Column(Float)
    is_active = Column(Boolean, default=True)

class RealtimeWipSummary(Base):
    __tablename__ = "realtime_wip_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_time = Column(Float, index=True)
    tool_group = Column(String, index=True)
    tool_id = Column(String, index=True, nullable=True)
    waiting_lots = Column(Integer, default=0)
    processing_lots = Column(Integer, default=0)
    avg_queue_time = Column(Float, default=0.0)


# -----------------------------------------------------------
# [설계도 12] KPI 스냅샷 — level별 4 테이블 (CSV 1:1; V6 migration)
# Legacy `kpi_snapshot` table replaced by kpi_fab/process/toolgroup/tool (V6).
# -----------------------------------------------------------
class KpiLevelBase(Base):
    __abstract__ = True

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True, nullable=True)
    snapshot_time = Column(Float)                      # ix_*_snapshot_time in subclass __table_args__
    scope = Column(String, index=True)                 # "*" | process_name | toolgroup_name | tool_id
    kpi_name = Column(String, index=True)              # rtf, throughput_24h, tat_min, ...
    value = Column(Float)                              # weighted sum or ratio
    window_minutes = Column(Integer, nullable=True)    # 60, 1440 등. 순간값이면 NULL
    numerator = Column(Float, nullable=True)
    denominator = Column(Float, nullable=True)
    meta = Column(Text, nullable=True)                 # optional JSON string (TEXT to match Flyway)


class KpiFab(KpiLevelBase):
    __tablename__ = "kpi_fab"
    __table_args__ = (
        Index("ix_kpi_fab_snapshot_time", "snapshot_time"),
        Index("ix_kpi_fab_lookup", "run_id", "scope", "kpi_name", "snapshot_time"),
    )


class KpiProcess(KpiLevelBase):
    __tablename__ = "kpi_process"
    __table_args__ = (
        Index("ix_kpi_process_snapshot_time", "snapshot_time"),
        Index("ix_kpi_process_lookup", "run_id", "scope", "kpi_name", "snapshot_time"),
    )


class KpiToolgroup(KpiLevelBase):
    __tablename__ = "kpi_toolgroup"
    __table_args__ = (
        Index("ix_kpi_toolgroup_snapshot_time", "snapshot_time"),
        Index("ix_kpi_toolgroup_lookup", "run_id", "scope", "kpi_name", "snapshot_time"),
    )


class KpiTool(KpiLevelBase):
    __tablename__ = "kpi_tool"
    __table_args__ = (
        Index("ix_kpi_tool_snapshot_time", "snapshot_time"),
        Index("ix_kpi_tool_lookup", "run_id", "scope", "kpi_name", "snapshot_time"),
    )


KPI_LEVEL_MODELS = (KpiFab, KpiProcess, KpiToolgroup, KpiTool)


# -----------------------------------------------------------
# MES FORWARD / WHAT-IF (input) — FabEnv scenario reset
# DDL: V001 (snapshots) + V002 mes_forward_whatif.sql
# Docs: docs/MES_FORWARD_WHATIF_SCHEMA.md
# -----------------------------------------------------------
class MesScenario(Base):
    __tablename__ = "mes_scenario"

    scenario_id = Column(String(64), primary_key=True)
    description = Column(Text, nullable=True)
    source_system = Column(String(128), nullable=True)
    mes_extract_batch_id = Column(String(128), nullable=True)
    t0_sim_minute = Column(Float, nullable=False)
    horizon_minutes = Column(Float, nullable=False)
    sim_start_calendar = Column(Date, nullable=True)
    mode = Column(String(32), nullable=False, default="FORWARD")  # FORWARD | WHATIF
    master_snapshot_hash = Column(String(64), nullable=True)
    baseline_scenario_id = Column(
        String(64), ForeignKey("mes_scenario.scenario_id", ondelete="SET NULL"), nullable=True
    )
    trigger_meta = Column(JSONB, nullable=True)
    use_master_lot_release = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="DRAFT")  # DRAFT|VALIDATED|RUNNING|DONE


class MesForwardInputEvent(Base):
    """Sparse forward inputs (HOLD/RELEASE/FAB_ARRIVAL). Not full TRACK_IN grid."""

    __tablename__ = "mes_forward_input_event"
    __table_args__ = (
        Index("ix_mes_forward_input_scenario_time", "scenario_id", "scheduled_time"),
        Index("ix_mes_forward_input_scenario_lot", "scenario_id", "lot_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False, default=0)
    lot_id = Column(String(128), nullable=False)
    route_id = Column(String(128), nullable=False)
    step_seq = Column(Integer, nullable=True)
    event_kind = Column(String(32), nullable=False)  # FAB_ARRIVAL | HOLD | RELEASE
    scheduled_time = Column(Float, nullable=False)
    tool_group = Column(String(128), nullable=True)
    tool_id = Column(String(128), nullable=True)
    priority = Column(Integer, nullable=True)
    due_date_sim = Column(Float, nullable=True)
    mes_row_hash = Column(String(64), nullable=True)
    source_line_no = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)


class MesLotReleasePlan(Base):
    """Lot releases in [t0, t0 + horizon] for FORWARD runs."""

    __tablename__ = "mes_lot_release_plan"
    __table_args__ = (Index("ix_mes_lot_release_scenario_time", "scenario_id", "release_time"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="CASCADE"), nullable=False)
    source_lot_release_id = Column(Integer, nullable=True)
    product_name = Column(String(128), nullable=False)
    route_name = Column(String(128), nullable=False)
    release_time = Column(Float, nullable=False)
    lots_count = Column(Integer, nullable=False, default=1)
    release_interval = Column(Float, nullable=True)
    lot_name_prefix = Column(String(128), nullable=True)
    lot_type = Column(String(128), nullable=True)
    priority = Column(Integer, nullable=True)
    due_date_sim = Column(Float, nullable=True)
    wafers_per_lot = Column(Integer, nullable=True)
    is_super_hot = Column(Boolean, nullable=False, default=False)
    mes_row_hash = Column(String(64), nullable=True)
    source_line_no = Column(Integer, nullable=True)


class MesWhatifAction(Base):
    """WHAT-IF overrides only (Agent / operator)."""

    __tablename__ = "mes_whatif_action"
    __table_args__ = (Index("ix_mes_whatif_scenario_time", "scenario_id", "effective_time"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False, default=0)
    action_kind = Column(String(64), nullable=False)
    effective_time = Column(Float, nullable=False)
    lot_id = Column(String(128), nullable=True)
    route_id = Column(String(128), nullable=True)
    step_seq = Column(Integer, nullable=True)
    tool_group = Column(String(128), nullable=True)
    tool_id = Column(String(128), nullable=True)
    payload_json = Column(JSONB, nullable=True)
    source = Column(String(32), nullable=False, default="AGENT")
    mes_row_hash = Column(String(64), nullable=True)


class MesOperatingEvent(Base):
    """Optional MES operating calendar (SCRAP/REWORK/HOLD)."""

    __tablename__ = "mes_operating_event"
    __table_args__ = (Index("ix_mes_operating_scenario_time", "scenario_id", "scheduled_time"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False, default=0)
    lot_id = Column(String(128), nullable=False)
    route_id = Column(String(128), nullable=True)
    step_seq = Column(Integer, nullable=True)
    event_kind = Column(String(32), nullable=False)
    scheduled_time = Column(Float, nullable=False)
    payload_json = Column(JSONB, nullable=True)
    mes_row_hash = Column(String(64), nullable=True)


# -----------------------------------------------------------
# WHAT-IF vs baseline KPI delta (simulation output)
# DDL: simulation/sql/flyway/V003__kpi_whatif_diff.sql
# -----------------------------------------------------------
class KpiWhatifDiff(Base):
    __tablename__ = "kpi_whatif_diff"
    __table_args__ = (
        Index("ix_kpi_whatif_diff_whatif_run", "whatif_run_id"),
        Index("ix_kpi_whatif_diff_scenario_time", "whatif_scenario_id", "snapshot_time"),
        Index("ix_kpi_whatif_diff_kpi", "whatif_scenario_id", "level", "scope", "kpi_name", "snapshot_time"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    whatif_scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="CASCADE"), nullable=False)
    baseline_scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="SET NULL"), nullable=True)
    baseline_run_id = Column(String(64), ForeignKey("simulation_run.run_id", ondelete="SET NULL"), nullable=True)
    whatif_run_id = Column(String(64), ForeignKey("simulation_run.run_id", ondelete="CASCADE"), nullable=False)
    level = Column(String(32), nullable=False)
    scope = Column(String(256), nullable=False)
    kpi_name = Column(String(128), nullable=False)
    snapshot_time = Column(Float, nullable=False)
    baseline_value = Column(Float, nullable=True)
    whatif_value = Column(Float, nullable=True)
    delta = Column(Float, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MesWipSnapshot(Base):
    __tablename__ = "mes_wip_snapshot"
    __table_args__ = (UniqueConstraint("scenario_id", "lot_id", name="uq_mes_wip_lot"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="CASCADE"), nullable=False)
    snapshot_time = Column(Float, nullable=False)
    lot_id = Column(String(128), nullable=False)
    route_id = Column(String(128), nullable=False)
    current_step_seq = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)  # QUEUING|PROCESSING|WAIT_TRANSPORT|HOLD|WAIT_BATCH
    tool_group = Column(String(128), nullable=True)
    tool_id = Column(String(128), nullable=True)
    queue_position = Column(Integer, nullable=True)
    due_date_sim = Column(Float, nullable=True)
    priority = Column(Integer, nullable=True)
    rem_steps = Column(Integer, nullable=True)
    processing_remaining_min = Column(Float, nullable=True)
    wafers_per_lot = Column(Integer, nullable=True)
    product = Column(String(128), nullable=True)
    is_super_hot = Column(Boolean, nullable=False, default=False)


class MesToolSnapshot(Base):
    __tablename__ = "mes_tool_snapshot"
    __table_args__ = (UniqueConstraint("scenario_id", "tool_id", name="uq_mes_tool_snapshot"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="CASCADE"), nullable=False)
    tool_id = Column(String(128), nullable=False)
    tool_group = Column(String(128), nullable=False)
    op_state = Column(String(32), nullable=False)  # IDLE|RUN|SETUP|DOWN_PM|DOWN_BM
    current_setup = Column(String(128), nullable=True)
    held_lot_id = Column(String(128), nullable=True)


class MesToolQueueSnapshot(Base):
    __tablename__ = "mes_tool_queue_snapshot"
    __table_args__ = (UniqueConstraint("scenario_id", "tool_id", "position", name="uq_mes_tool_queue_pos"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="CASCADE"), nullable=False)
    tool_id = Column(String(128), nullable=False)
    position = Column(Integer, nullable=False)
    lot_id = Column(String(128), nullable=False)
    route_id = Column(String(128), nullable=True)
    step_seq = Column(Integer, nullable=True)
    due_date_sim = Column(Float, nullable=True)
    priority = Column(Integer, nullable=True)


class MesCqtSnapshot(Base):
    __tablename__ = "mes_cqt_snapshot"
    __table_args__ = (UniqueConstraint("scenario_id", "lot_id", name="uq_mes_cqt_lot"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="CASCADE"), nullable=False)
    lot_id = Column(String(128), nullable=False)
    anchor_step = Column(Integer, nullable=True)
    target_step = Column(Integer, nullable=False)
    deadline_time = Column(Float, nullable=False)
    started_at = Column(Float, nullable=False)


class MesScenarioRun(Base):
    __tablename__ = "mes_scenario_run"
    __table_args__ = (
        UniqueConstraint("scenario_id", "simulation_run_id", name="uq_mes_scenario_run"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scenario_id = Column(String(64), ForeignKey("mes_scenario.scenario_id", ondelete="CASCADE"), nullable=False)
    simulation_run_id = Column(String(64), ForeignKey("simulation_run.run_id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    validation_report = Column(JSONB, nullable=True)