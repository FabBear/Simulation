package com.skala.fab.service;

import com.skala.fab.dto.DispatchRequest;
import com.skala.fab.dto.StatusResponse;
import com.skala.fab.dto.UiEventRequest;
import com.skala.fab.dto.WhatIfRequest;
import com.skala.fab.dto.WhatIfResponse;

import java.util.Map;

public interface SimulationEngineGateway {
    Map<String, Object> root();
    StatusResponse status();
    StatusResponse step(String mode);
    StatusResponse reset();
    StatusResponse pause();
    StatusResponse resume();
    StatusResponse dispatch(DispatchRequest request);
    Map<String, Object> layout();
    Map<String, Object> uiEvent(UiEventRequest request);
    Map<String, Object> fileWriteCheck();
    WhatIfResponse whatIf(WhatIfRequest request);
}
