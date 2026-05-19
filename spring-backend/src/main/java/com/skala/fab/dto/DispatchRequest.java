package com.skala.fab.dto;

import jakarta.validation.constraints.NotNull;

public record DispatchRequest(@NotNull Integer action_idx) {}
