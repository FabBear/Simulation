package com.skala.fab.dto;

import jakarta.validation.constraints.NotNull;

import java.util.Map;

public record WhatIfRequest(
    @NotNull Map<String, Object> snapshot,
    Map<String, Object> action,
    Double horizon_min,
    Integer master_seed,
    String mode
) {}
