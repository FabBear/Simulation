package com.skala.fab.service;

import com.skala.fab.dto.DispatchRequest;
import com.skala.fab.dto.MachineLayoutItem;
import com.skala.fab.dto.StatusResponse;
import com.skala.fab.dto.UiEventRequest;
import com.skala.fab.dto.WhatIfRequest;
import com.skala.fab.dto.WhatIfResponse;
import com.skala.fab.engine.EngineSnapshot;
import com.skala.fab.engine.SimulationEngine;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

@Component
@ConditionalOnProperty(name = "engine.mode", havingValue = "java")
public class JavaEngineGateway implements SimulationEngineGateway {
    private final SimulationEngine engine;
    private final EngineSnapshotMapper mapper;

    public JavaEngineGateway(SimulationEngine engine, EngineSnapshotMapper mapper) {
        this.engine = engine;
        this.mapper = mapper;
        mapper.resetSequence();
        engine.reset();
    }

    @Override
    public Map<String, Object> root() {
        EngineSnapshot s = engine.status();
        return Map.of(
            "status", "Server is running",
            "simulation_time", s.simTime()
        );
    }

    @Override
    public StatusResponse status() {
        return mapper.toStatus(engine.status());
    }

    @Override
    public StatusResponse step(String mode) {
        return mapper.toStatus(engine.step());
    }

    @Override
    public StatusResponse reset() {
        mapper.resetSequence();
        return mapper.toStatus(engine.reset());
    }

    @Override
    public StatusResponse pause() {
        return mapper.toStatus(engine.pause());
    }

    @Override
    public StatusResponse resume() {
        return mapper.toStatus(engine.resume());
    }

    @Override
    public StatusResponse dispatch(DispatchRequest request) {
        return mapper.toStatus(engine.dispatch(request.action_idx()));
    }

    @Override
    public Map<String, Object> layout() {
        return Map.of(
            "Etch", List.of(
                new MachineLayoutItem("ETCH_01", 1, 1, 75.0),
                new MachineLayoutItem("ETCH_02", 1, 0, 25.0)
            ),
            "Photo", List.of(
                new MachineLayoutItem("PHOTO_01", 1, 0, 35.0)
            )
        );
    }

    @Override
    public Map<String, Object> uiEvent(UiEventRequest request) {
        return Map.of("ok", true);
    }

    @Override
    public Map<String, Object> fileWriteCheck() {
        return Map.of(
            "ok", true,
            "path", "in-memory-java-engine"
        );
    }

    @Override
    public WhatIfResponse whatIf(WhatIfRequest request) {
        return new WhatIfResponse(
            "NOT_SUPPORTED",
            Map.of(),
            Map.of(),
            Map.of(),
            Map.of("reason", "what-if is only available in python engine mode")
        );
    }
}
