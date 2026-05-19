package com.skala.fab.service;

import com.skala.fab.dto.DispatchRequest;
import com.skala.fab.dto.StatusResponse;
import com.skala.fab.dto.UiEventRequest;
import com.skala.fab.dto.WhatIfRequest;
import com.skala.fab.dto.WhatIfResponse;
import org.springframework.stereotype.Service;

import java.util.Map;

@Service
public class SimulationFacadeService {
    private final SimulationEngineGateway engineGateway;

    public SimulationFacadeService(SimulationEngineGateway engineGateway) {
        this.engineGateway = engineGateway;
    }

    public Map<String, Object> root() {
        return engineGateway.root();
    }

    public StatusResponse status() {
        return engineGateway.status();
    }

    public StatusResponse step(String mode) {
        return engineGateway.step(mode);
    }

    public StatusResponse reset() {
        return engineGateway.reset();
    }

    public StatusResponse pause() {
        return engineGateway.pause();
    }

    public StatusResponse resume() {
        return engineGateway.resume();
    }

    public StatusResponse dispatch(DispatchRequest request) {
        return engineGateway.dispatch(request);
    }

    public Map<String, Object> layout() {
        return engineGateway.layout();
    }

    public Map<String, Object> uiEvent(UiEventRequest request) {
        return engineGateway.uiEvent(request);
    }

    public Map<String, Object> fileWriteCheck() {
        return engineGateway.fileWriteCheck();
    }

    public WhatIfResponse whatIf(WhatIfRequest request) {
        return engineGateway.whatIf(request);
    }
}
