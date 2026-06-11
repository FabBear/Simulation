package com.skala.fab.engine;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Random;

/**
 * Stage 3 skeleton:
 * SimPy parity replacement point.
 */
@Component
public class JavaSimulationEngine implements SimulationEngine {
    private static final String MACHINE_NAME = "ETCH_01";
    private static final Random RND = new Random(42);

    private double simTime = 0.0;
    private boolean paused = true;
    private boolean done = false;
    private final List<LotState> activeLots = new ArrayList<>();
    private final List<LotState> waitingQueue = new ArrayList<>();

    @Override
    public synchronized EngineSnapshot reset() {
        simTime = 0.0;
        paused = true;
        done = false;
        activeLots.clear();
        waitingQueue.clear();
        waitingQueue.add(new LotState("Lot_Product_3_1", "Route_Product_E3", 22, 22, 1000.0, 10, "Queuing"));
        waitingQueue.add(new LotState("Lot_Product_4_1", "Route_Product_E4", 18, 18, 900.0, 8, "Queuing"));
        waitingQueue.add(new LotState("Lot_Product_5_1", "Route_Product_E5", 16, 16, 800.0, 6, "Queuing"));
        activeLots.add(waitingQueue.remove(0));
        return status();
    }

    @Override
    public synchronized EngineSnapshot pause() {
        paused = true;
        return status();
    }

    @Override
    public synchronized EngineSnapshot resume() {
        paused = false;
        return status();
    }

    @Override
    public synchronized EngineSnapshot step() {
        if (done || paused) {
            return status();
        }

        // Periodically generate a queued lot so decision queue stays active.
        if (((int) simTime) % 5 == 0 && waitingQueue.size() < 6) {
            int p = 3 + RND.nextInt(10);
            int steps = 10 + RND.nextInt(8);
            waitingQueue.add(new LotState(
                "Lot_Product_" + (RND.nextInt(4) + 2) + "_" + ((int) simTime + 1),
                "Route_Product_E" + (RND.nextInt(4) + 2),
                steps,
                steps,
                900.0 + RND.nextInt(200),
                p,
                "Queuing"
            ));
        }

        if (activeLots.isEmpty() && !waitingQueue.isEmpty()) {
            activeLots.add(waitingQueue.remove(0));
        }

        simTime += 1.0;
        if (!activeLots.isEmpty()) {
            LotState l = activeLots.get(0);
            int next = Math.max(0, l.remSteps() - 1);
            String status = next == 0 ? "Done" : "Processing";
            activeLots.set(0, new LotState(l.lotName(), l.routeId(), next, l.totalSteps(), l.dueDate(), l.priority(), status));
            if (next == 0) {
                activeLots.remove(0);
            }
        }

        if (simTime >= 90.0 || (activeLots.isEmpty() && waitingQueue.isEmpty())) {
            done = true;
            paused = true;
        }
        return status();
    }

    @Override
    public synchronized EngineSnapshot dispatch(int actionIndex) {
        if (paused) {
            paused = false;
        }
        if (!waitingQueue.isEmpty()) {
            int idx = Math.max(0, Math.min(actionIndex, waitingQueue.size() - 1));
            LotState selected = waitingQueue.remove(idx);
            if (activeLots.isEmpty()) {
                activeLots.add(selected);
            } else {
                waitingQueue.add(0, selected);
            }
        }
        return step();
    }

    @Override
    public synchronized EngineSnapshot status() {
        List<LotState> queue = waitingQueue.stream()
            .sorted(Comparator.comparingInt(LotState::priority).reversed())
            .limit(6)
            .toList();
        String targetMachine = queue.isEmpty() ? null : MACHINE_NAME;
        return new EngineSnapshot(simTime, paused, done, targetMachine, queue, List.copyOf(activeLots));
    }
}
