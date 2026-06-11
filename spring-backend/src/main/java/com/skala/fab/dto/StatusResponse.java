package com.skala.fab.dto;

import java.util.List;

public record StatusResponse(
    Integer status_seq,
    Double time,
    Double sim_now_min,
    Boolean is_paused,
    Boolean is_done,
    String target_machine,
    List<QueueItem> queue,
    List<ActiveLotItem> active_lots,
    String progress_signature,
    KpiDto kpi,
    String mode
) {}
