package com.skala.fab.controller;

import com.skala.fab.dto.DispatchRequest;
import com.skala.fab.dto.StatusResponse;
import com.skala.fab.dto.UiEventRequest;
import com.skala.fab.dto.WhatIfRequest;
import com.skala.fab.dto.WhatIfResponse;
import com.skala.fab.service.SimulationFacadeService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.Map;

@RestController
@RequestMapping
public class SimulationController {
    private final SimulationFacadeService service;

    public SimulationController(SimulationFacadeService service) {
        this.service = service;
    }

    @GetMapping("/")
    public Map<String, Object> root() {
        return service.root();
    }

    @GetMapping("/api/status")
    public StatusResponse status() {
        return service.status();
    }

    @PostMapping("/api/step")
    public StatusResponse step(@RequestParam(name = "mode", defaultValue = "sequential") String mode) {
        return service.step(mode);
    }

    @PostMapping("/api/control/reset")
    public StatusResponse reset() {
        return service.reset();
    }

    @PostMapping("/api/control/pause")
    public StatusResponse pause() {
        return service.pause();
    }

    @PostMapping("/api/control/resume")
    public StatusResponse resume() {
        return service.resume();
    }

    @PostMapping("/api/dispatch")
    public StatusResponse dispatch(@Valid @RequestBody DispatchRequest request) {
        return service.dispatch(request);
    }

    @GetMapping("/api/layout")
    public Map<String, Object> layout() {
        return service.layout();
    }

    @PostMapping("/api/debug/ui-event")
    public Map<String, Object> uiEvent(@RequestBody UiEventRequest request) {
        return service.uiEvent(request);
    }

    @GetMapping("/api/debug/file-write-check")
    public Map<String, Object> fileWriteCheck() {
        return service.fileWriteCheck();
    }

    @PostMapping("/api/v1/simulate/what-if")
    public WhatIfResponse whatIf(@Valid @RequestBody WhatIfRequest request) {
        return service.whatIf(request);
    }
}
