package com.skala.fab.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.skala.fab.dto.DispatchRequest;
import com.skala.fab.dto.StatusResponse;
import com.skala.fab.dto.UiEventRequest;
import com.skala.fab.dto.WhatIfRequest;
import com.skala.fab.dto.WhatIfResponse;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

@Component
@ConditionalOnProperty(name = "engine.mode", havingValue = "python", matchIfMissing = true)
public class PythonBridgeEngineGateway implements SimulationEngineGateway {
    private final PythonEngineClient engineClient;
    private final ObjectMapper objectMapper;

    public PythonBridgeEngineGateway(PythonEngineClient engineClient, ObjectMapper objectMapper) {
        this.engineClient = engineClient;
        this.objectMapper = objectMapper;
    }

    @Override
    public Map<String, Object> root() {
        return asMap(engineClient.get("/"));
    }

    @Override
    public StatusResponse status() {
        return objectMapper.convertValue(engineClient.get("/api/status"), StatusResponse.class);
    }

    @Override
    public StatusResponse step(String mode) {
        return objectMapper.convertValue(engineClient.post("/api/step?mode=" + mode), StatusResponse.class);
    }

    @Override
    public StatusResponse reset() {
        return objectMapper.convertValue(engineClient.post("/api/control/reset"), StatusResponse.class);
    }

    @Override
    public StatusResponse pause() {
        return objectMapper.convertValue(engineClient.post("/api/control/pause"), StatusResponse.class);
    }

    @Override
    public StatusResponse resume() {
        return objectMapper.convertValue(engineClient.post("/api/control/resume"), StatusResponse.class);
    }

    @Override
    public StatusResponse dispatch(DispatchRequest request) {
        JsonNode node = engineClient.post("/api/dispatch", Map.of("action_idx", request.action_idx()));
        return objectMapper.convertValue(node, StatusResponse.class);
    }

    @Override
    public Map<String, Object> layout() {
        return asMap(engineClient.get("/api/layout"));
    }

    @Override
    public Map<String, Object> uiEvent(UiEventRequest request) {
        JsonNode node = engineClient.post(
            "/api/debug/ui-event",
            Map.of(
                "event", request.event(),
                "details", request.details() == null ? Map.of() : request.details()
            )
        );
        return asMap(node);
    }

    @Override
    public Map<String, Object> fileWriteCheck() {
        return asMap(engineClient.get("/api/debug/file-write-check"));
    }

    @Override
    public WhatIfResponse whatIf(WhatIfRequest request) {
        Map<String, Object> body = new HashMap<>();
        body.put("snapshot", request.snapshot());
        body.put("action", request.action());
        body.put("horizon_min", request.horizon_min() == null ? 720.0 : request.horizon_min());
        body.put("master_seed", request.master_seed() == null ? 42 : request.master_seed());
        body.put("mode", request.mode() == null ? "sequential" : request.mode());
        JsonNode node = engineClient.post(
            "/api/v1/simulate/what-if",
            body
        );
        return objectMapper.convertValue(node, WhatIfResponse.class);
    }

    private Map<String, Object> asMap(JsonNode node) {
        return objectMapper.convertValue(node, new TypeReference<>() {});
    }
}
