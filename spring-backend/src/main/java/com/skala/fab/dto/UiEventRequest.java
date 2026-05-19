package com.skala.fab.dto;

import java.util.Map;

public record UiEventRequest(String event, Map<String, Object> details) {}
