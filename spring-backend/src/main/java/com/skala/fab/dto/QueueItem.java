package com.skala.fab.dto;

public record QueueItem(
    Integer index,
    String lot_name,
    String product,
    Integer priority,
    Integer rem_steps,
    String due_date,
    String q_danger
) {}
