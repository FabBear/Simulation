package com.skala.fab.dto;

public record KpiDto(
    Integer finished_lots,
    Double avg_tat,
    Integer q_viol,
    Integer processing_lots
) {}
