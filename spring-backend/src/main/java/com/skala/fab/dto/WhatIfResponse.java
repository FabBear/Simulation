package com.skala.fab.dto;

import java.util.Map;

public record WhatIfResponse(
    String status,
    Map<String, Object> baseline_metrics,
    Map<String, Object> action_metrics,
    Map<String, Object> delta,
    Map<String, Object> metadata
) {}
