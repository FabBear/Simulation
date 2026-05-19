package com.skala.fab.dto;

public record ActiveLotItem(
    String lot_name,
    String product,
    Integer rem_steps,
    Integer total_steps,
    String due_date,
    String status
) {}
