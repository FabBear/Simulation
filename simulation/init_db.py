import pandas as pd
import numpy as np
import os
from database import SessionLocal, create_tables
from models import ToolGroup, ProcessStep, PMEvent, BreakdownEvent, LotRelease, SetupInfo, TransportTime

# -----------------------------------------------------------
# [헬퍼 함수] 엑셀의 빈칸(NaN)을 DB의 NULL(None)로 바꿔주는 함수
# -----------------------------------------------------------
def clean(value):
    if pd.isna(value) or value == '':
        return None
    return value

def clean_bool(value):
    if str(value).upper() == 'YES':
        return True
    return False

# -----------------------------------------------------------
# 1. 장비 데이터 로딩 (SMT_3_Toolgroups.xlsx)
# -----------------------------------------------------------
def import_toolgroups(db):
    print("📥 ToolGroup 데이터 로딩 중...")
    df = pd.read_excel("data/SMT_3_Toolgroups.xlsx")
    
    for _, row in df.iterrows():
        tool = ToolGroup(
            toolgroup_name=row['TOOLGROUP'],
            num_tools=row['NUMBER OF TOOLS'],
            location=row['TOOLGROUPLOCATION'],
            is_cascading=clean_bool(row.get('CASCADINGTOOL')),
            is_batching=clean_bool(row.get('BATCHINGTOOL')), # 오타 수정 (BACTHINGTOOL -> BATCHINGTOOL)
            batch_criterion=clean(row.get('BATCHCRITERION')),
            batch_unit=clean(row.get('BATCHING UNIT')),
            loading_time=clean(row.get('LOADINGTIME')),
            unloading_time=clean(row.get('UNLOADINGTIME')),
            dispatch_rule=clean(row.get('DISPATCHING')),
            ranking_1=clean(row.get('Ranking 1')),
            ranking_2=clean(row.get('Ranking 2')),
            ranking_3=clean(row.get('Ranking 3')),
            tool_wakeup_ranking=clean(row.get('TOOL WAKE UP Ranking'))
        )
        db.add(tool)
    db.commit()
    print(f"✅ ToolGroup {len(df)}개 저장 완료!")

# -----------------------------------------------------------
# 2. 공정(Route) 데이터 로딩 (여러 파일 반복)
# -----------------------------------------------------------
# -----------------------------------------------------------
# 2. 공정(Route) 데이터 로딩 (Uniform 분포 반영 수정됨)
# -----------------------------------------------------------
def import_routes(db):
    # Route 파일 목록
    route_files = [
        "SMT_3_Route_Product_3.xlsx",
        "SMT_3_Route_Product_4.xlsx",
        "SMT_3_Route_Product_E3.xlsx"
    ]
    
    print("📥 Route(ProcessStep) 데이터 로딩 중...")
    total_steps = 0
    
    for filename in route_files:
        # 엑셀 파일 읽기
        df = pd.read_excel(f"data/{filename}")
        
        # [중요] 컬럼 이름의 앞뒤 공백을 제거합니다. 
        # (엑셀에서 'OFFSET ' 처럼 공백이 숨어있을 수 있어서 필수입니다)
        df.columns = df.columns.str.strip()
        
        for _, row in df.iterrows():
            # Batch Min/Max 정제
            b_min = clean(row.get('BATCH MINIMUM'))
            b_max = clean(row.get('BATCH MAXIMUM'))
            
            # 엑셀 데이터 읽기 (사진에서 확인한 컬럼명 기준)
            # TOOLGROUP 컬럼이 붙어있는지 떨어져있는지 확인 (보통 붙어있음)
            tg_name = row.get('TOOLGROUP') if 'TOOLGROUP' in row else row.get('TOOL GROUP')

            step = ProcessStep(
                route_id=row['ROUTE'],
                step_seq=row['STEP'],
                step_name=row['STEP DESCRIPTION'],
                area=row['AREA'],
                target_tool_group=tg_name,
                
                # 👇 [핵심 수정] Uniform 분포 데이터 매핑
                proc_unit=clean(row.get('PROCESSING UNIT')),
                proc_time_dist=clean(row.get('PROCESSINGTIME DISTRIBUTION')), # 'uniform'
                proc_time_mean=clean(row.get('MEAN')),   # 평균 (501.33 등)
                proc_time_offset=clean(row.get('OFFSET')), # 편차 범위 (25.06 등)
                proc_time_unit=clean(row.get('PT UNITS')),
                
                # (Standard Deviation은 이제 안 씁니다)
                # proc_time_std=... (삭제)
                
                cascading_interval=clean(row.get('CASCADING INTERVAL')),
                batch_min=int(b_min) if b_min else None,
                batch_max=int(b_max) if b_max else None,
                
                setup_id=clean(row.get('SETUP NAME')), # 헤더가 SETUP인지 SETUP NAME인지 확인 (보통 SETUP NAME)
                setup_policy=clean(row.get('WHEN')),
                setup_time_mean=clean(row.get('SETUP TIME')),
                
                # 엑셀에 OFFSET 컬럼이 2개라면 pandas가 자동으로 두 번째에 .1을 붙입니다.
                # 보통 뒤쪽에 있는 Setup 관련 Offset은 'OFFSET.1'이 됩니다.
                setup_time_offset=clean(row.get('OFFSET.1')), 
                
                ltl_dedication_step=clean(row.get('STEP FOR LTL DEDICATION')),
                rework_prob=clean(row.get('REWORK PROBABILITY in %')),
                rework_target_step=clean(row.get('STEP FOR REWORK')),
                sampling_prob=clean(row.get('PROCESSING PROBABILITY in % (Sampling)')),
                
                cqt_anchor_step=(
                    int(row['STEP']) if pd.notna(row.get('CQT')) and pd.notna(row.get('STEP')) else None
                ),
                cqt_target_step=clean(row.get('STEP FOR CRITICAL QUEUE TIME')),
                cqt_start_step=clean(row.get('STEP FOR CRITICAL QUEUE TIME')),
                cqt_limit=clean(row.get('CQT')),
                cqt_unit=clean(row.get('CQTUNITS'))
            )
            db.add(step)
            total_steps += 1
            
    db.commit()
    print(f"✅ 총 {total_steps}개의 공정 스텝 저장 완료!")

# -----------------------------------------------------------
# 3. 이벤트(PM, Breakdown) 데이터 로딩
# -----------------------------------------------------------
def import_events(db):
    print("📥 PM & Breakdown 데이터 로딩 중...")
    
    # PM 로딩
    df_pm = pd.read_excel("data/SMT_3_PM.xlsx")
    for _, row in df_pm.iterrows():
        pm = PMEvent(
            pm_name=row['PM EVENT NAME'],
            target_tool_group=row['TYPE NAME'], # TOOLGROUP 이름과 매칭
            pm_type=row['PM TYPE'],
            mtbf=clean(row.get('MTBeforePM')),
            mtbf_unit=clean(row.get('MTBPM UNITS')),
            duration_mean=clean(row.get('MEAN')),
            duration_offset=clean(row.get('OFFSET')),
            duration_dist=clean(row.get('TTR DISTRIBUTION')),
            duration_unit=clean(row.get('TTR UNITS')),
            first_occurrence=clean(row.get('FOA')),
            foa_dist=clean(row.get('FIRST ONE AT DISTRIBUTION')),
            foa_unit=clean(row.get('FOA UNITS'))
        )
        db.add(pm)

    # Breakdown 로딩
    df_bd = pd.read_excel("data/SMT_3_Breakdown.xlsx")
    for _, row in df_bd.iterrows():
        bd = BreakdownEvent(
            event_name=row['DOWN EVENT NAME'],
            scope=row['DOWN EVENT VALID FOR TYPE'],
            target_name=row['TYPE NAME'],
            ttf_dist=clean(row.get('TTF DISTRIBUTION')),
            mttf_mean=clean(row.get('MTTF')),
            mttf_unit=clean(row.get('MTTF UNITS')),
            ttr_dist=clean(row.get('TTR DISTRIBUTION')),
            mttr_mean=clean(row.get('MTTR')),
            mttr_unit=clean(row.get('MTTR UNITS')),
            foa_dist=clean(row.get('FIRST ONE AT DISTRIBUTION')),
            foa_mean=clean(row.get('FOA')),
            foa_unit=clean(row.get('FOA UNITS'))
        )
        db.add(bd)
        
    db.commit()
    print("✅ 이벤트 데이터 저장 완료!")

# -----------------------------------------------------------
# 4. 셋업 & 이동 데이터 로딩
# -----------------------------------------------------------
# init_db.py 파일의 import_setup_transport 함수 교체

def import_setup_transport(db):
    print("📥 Setup & Transport 데이터 로딩 중...")
    
    # Setup 데이터 로딩
    df_setup = pd.read_excel("data/SMT_3_Setups.xlsx")
    for _, row in df_setup.iterrows():
        
        # 1. Setup Group 처리 (빈칸이면 None, 있으면 문자열)
        s_group = row['SETUP GROUP NAME']
        if pd.isna(s_group) or s_group == '':
            s_group = None
        else:
            s_group = str(s_group)

        # 2. Setup Name 처리 (에러가 났던 부분! 강제로 문자열 변환)
        curr_setup = str(row['CURRENT SETUP']) if pd.notna(row['CURRENT SETUP']) else None
        new_setup = str(row['NEW SETUP']) if pd.notna(row['NEW SETUP']) else None

        # 3. Setup Time 처리 (숫자 뒤에 ' min' 같은 글자가 붙어있을 수 있음)
        # 엑셀에 '7 min'이라고 적혀있으면 파이썬이 문자로 읽을 수 있습니다. 숫자만 남겨야 합니다.
        raw_time = row['SETUP TIME']
        final_time = 0.0
        
        if isinstance(raw_time, (int, float)):
             final_time = float(raw_time)
        else:
            # "7 min" 같은 문자열에서 숫자만 추출 시도 (혹시 모를 에러 방지)
            try:
                final_time = float(str(raw_time).replace(' min', '').strip())
            except:
                final_time = 0.0

        setup = SetupInfo(
            setup_group=s_group,
            from_setup=curr_setup,  # DE_BE_13_1 (문자열)
            to_setup=new_setup,     # DE_BE_13_2 (문자열)
            setup_time=final_time,  # 7.0 (실수)
            setup_unit=str(row['ST UNITS']),
            min_run_length=clean(row.get('MINMAL NUMBER OF RUNS'))
        )
        db.add(setup)
        
    # Transport (이 부분은 기존과 동일하지만 함께 실행되어야 함)
    df_trans = pd.read_excel("data/SMT_3_Transport.xlsx")
    for _, row in df_trans.iterrows():
        trans = TransportTime(
            from_loc=row['FROM LOCATION'],
            to_loc=row['TO LOCATION'],
            dist_type=row['TRANSPORTTIME DISTRIBUTION'],
            mean_time=row['MEAN'],
            offset_time=row['OFFSET'],
            time_unit=row['TT UNITS']
        )
        db.add(trans)
        
    db.commit()
    print("✅ Setup & Transport 저장 완료!")

# -----------------------------------------------------------
# 5. Lot Release 데이터 로딩
# -----------------------------------------------------------
# init_db.py 파일의 import_lot_release 함수 교체

# init_db.py 의 import_lot_release 함수를 이걸로 바꾸세요!

def import_lot_release(db):
    print("📥 Lot Release 데이터 로딩 중...")
    
    # Engineering xlsx is 8-year discrete benchmark — not used by FabEnv batch sim.
    files = ["SMT_3_Lotrelease.xlsx"]
    
    for filename in files:
        print(f"   📄 파일 읽는 중: {filename}")
        df = pd.read_excel(f"data/{filename}")
        df.columns = df.columns.str.strip() # 컬럼 공백 제거
        
        for index, row in df.iterrows():
            try:
                # [안전장치 1] 제품 이름이 없으면(빈 행 or 이상한 행) 건너뛰기
                p_name = row.get('PRODUCT NAME')
                if pd.isna(p_name) or str(p_name).strip() == '':
                    continue

                # [안전장치 2] 숫자 변환 헬퍼 (큰 숫자가 오면 0으로 처리하거나 에러 확인)
                def safe_int(val):
                    if pd.isna(val) or val == '': return None
                    try:
                        # 1.0 처럼 소수점이 붙은 문자일 수도 있어서 float -> int 변환
                        return int(float(val))
                    except:
                        return None # 숫자가 아니면 None

                # 데이터 읽기
                lot = LotRelease(
                    product_name = p_name,
                    route_name = row.get('ROUTE NAME'),
                    lot_type = clean(row.get('LOT NAME/TYPE')),
                    
                    # 여기가 에러 의심 구간! (Priority, Wafers 등)
                    priority = safe_int(row.get('PRIORITY')),
                    wafers_per_lot = safe_int(row.get('WAFERS PER LOT')),
                    lots_per_release = safe_int(row.get('LOTS PER RELEASE')),
                    
                    is_super_hot_lot = clean(row.get('SUPERHOTLOT')),
                    start_date = str(row.get('START DATE')),
                    due_date = str(row.get('DUE DATE')),
                    
                    release_dist = clean(row.get('RELEASE DISTRIBUTION')),
                    release_interval = clean(row.get('RELEASE INTERVAL')), # Float는 범위가 넓어서 괜찮음
                    release_unit = clean(row.get('R UNITS'))
                )
                db.add(lot)
            
            except Exception as e:
                # 🚨 에러가 나면 어떤 데이터인지 보여줍니다!
                print(f"\n❌ [에러 발생] 파일: {filename}, 행 번호: {index + 2}")
                print(f"   데이터: {row.to_dict()}")
                print(f"   이유: {e}\n")
                # 여기서 멈추지 않고 다음 행으로 넘어갈지, 멈출지 결정 (일단 에러 내고 멈춤)
                raise e
            
    db.commit()
    print("✅ Lot Release 저장 완료!")

# -----------------------------------------------------------
# [메인 실행]
# -----------------------------------------------------------
if __name__ == "__main__":
    # [추가!] 기존에 잘못 만들어진 테이블이 있다면 싹 지웁니다.
    # 주의: 안에 들어있던 데이터도 다 날아갑니다 (어차피 엑셀에서 다시 넣으면 됩니다).
    from models import Base
    from database import engine

    # 1. 테이블 생성 (이제 깨끗한 상태에서 올바르게 다시 만듭니다)
    print("🏗️ 테이블 새로 생성 중...")
    create_tables()
    
    # 2. 데이터베이스 세션 열기
    db = SessionLocal()
    
    try:
        # 순서대로 실행 (FK 관계 때문에 ToolGroup 먼저 넣는게 좋음)
        import_toolgroups(db)
        import_routes(db)
        import_events(db)
        import_setup_transport(db)
        import_lot_release(db)
        
        print("\n🎉 모든 데이터가 성공적으로 DB에 저장되었습니다!")
        
    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")
        import traceback
        traceback.print_exc() # 에러가 나면 어디서 났는지 자세히 보여줌
        
    finally:
        db.close()