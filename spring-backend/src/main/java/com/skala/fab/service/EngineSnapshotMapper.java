package com.skala.fab.service;

import com.skala.fab.dto.ActiveLotItem;
import com.skala.fab.dto.KpiDto;
import com.skala.fab.dto.QueueItem;
import com.skala.fab.dto.StatusResponse;
import com.skala.fab.engine.EngineSnapshot;
import com.skala.fab.engine.LotState;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

@Component
public class EngineSnapshotMapper {
    private final AtomicInteger sequence = new AtomicInteger(0);
    /** When simulation state is unchanged between polls, reuse seq (fixes PAUSE + 1s status polling). */
    private volatile String lastSnapshotFingerprint;
    private volatile int lastEmittedSeq;

    public void resetSequence() {
        sequence.set(0);
        lastSnapshotFingerprint = null;
        lastEmittedSeq = 0;
    }

    public StatusResponse toStatus(EngineSnapshot snapshot) {
        List<ActiveLotItem> activeLots = snapshot.activeLots().stream()
            .map(this::toActiveLot)
            .collect(Collectors.toCollection(ArrayList::new));
        List<QueueItem> queue = toQueue(snapshot.decisionQueue());

        int processing = (int) activeLots.stream().filter(l -> "Processing".equalsIgnoreCase(l.status())).count();
        // Do not derive finished from status_seq: it changes every poll and breaks fingerprint stability.
        int finished = (int) activeLots.stream().filter(l -> "Done".equalsIgnoreCase(l.status())).count();
        double avgTat = activeLots.isEmpty()
            ? 0.0
            : activeLots.stream().mapToInt(ActiveLotItem::total_steps).average().orElse(0.0);

        String signature = activeLots.stream()
            .sorted(Comparator.comparing(ActiveLotItem::lot_name))
            .limit(6)
            .map(l -> l.lot_name() + ":" + l.rem_steps() + ":" + l.status())
            .collect(Collectors.joining("|"));

        KpiDto kpi = new KpiDto(finished, round(avgTat), 0, processing);
        String fp = buildFingerprint(snapshot, queue, signature);
        boolean deduped = fp.equals(lastSnapshotFingerprint) && lastEmittedSeq > 0;
        int nextSeq;
        if (deduped) {
            nextSeq = lastEmittedSeq;
        } else {
            nextSeq = sequence.incrementAndGet();
            lastSnapshotFingerprint = fp;
            lastEmittedSeq = nextSeq;
        }
        return new StatusResponse(
            nextSeq,
            round(snapshot.simTime()),
            round(snapshot.simTime()),
            snapshot.paused(),
            snapshot.done(),
            snapshot.targetMachine(),
            queue,
            activeLots,
            signature,
            kpi,
            "sequential"
        );
    }

    /** Snapshot-only fields; must not depend on status_seq or other poll-varying derived KPI hacks. */
    private static String buildFingerprint(
        EngineSnapshot snapshot,
        List<QueueItem> queue,
        String progressSignature
    ) {
        String q = queue.stream()
            .map(qi -> qi.index() + ":" + qi.lot_name() + ":" + qi.rem_steps())
            .collect(Collectors.joining(","));
        return round(snapshot.simTime())
            + "|" + snapshot.paused()
            + "|" + snapshot.done()
            + "|" + (snapshot.targetMachine() == null ? "" : snapshot.targetMachine())
            + "|" + progressSignature
            + "|" + q;
    }

    private ActiveLotItem toActiveLot(LotState lot) {
        return new ActiveLotItem(
            lot.lotName(),
            lot.routeId(),
            lot.remSteps(),
            lot.totalSteps(),
            String.format("%.1f", lot.dueDate()),
            lot.status()
        );
    }

    private List<QueueItem> toQueue(List<LotState> queueLots) {
        List<QueueItem> out = new ArrayList<>();
        for (int i = 0; i < queueLots.size(); i++) {
            LotState lot = queueLots.get(i);
            out.add(new QueueItem(
                i,
                lot.lotName(),
                lot.routeId(),
                lot.priority(),
                lot.remSteps(),
                String.format("%.1f", lot.dueDate()),
                String.format("%.2f", Math.max(0.0, 1000.0 - lot.dueDate()) / 100.0)
            ));
        }
        return out;
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
