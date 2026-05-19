package com.skala.fab.dto;

public record MachineLayoutItem(
    String name,
    Integer total,
    Integer busy,
    Double utilization
) {}
