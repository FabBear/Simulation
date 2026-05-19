package com.skala.fab.engine;

public interface SimulationEngine {
    EngineSnapshot reset();
    EngineSnapshot pause();
    EngineSnapshot resume();
    EngineSnapshot step();
    EngineSnapshot dispatch(int actionIndex);
    EngineSnapshot status();
}
