package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

@Entity
@Table(name = "simulation_run")
public class SimulationRunEntity {
    @Id
    private String runId;
    private String sourcePath;
    private Instant importedAt;
    private Double simEndMinutes;
    private String note;
}
