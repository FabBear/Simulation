package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "simulation_log")
public class SimulationLogEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String runId;
    private String lotId;
    private String product;
    private String routeId;
    private Integer stepSeq;
    private String stepName;
    private String toolGroup;
    private String toolId;
    private Double arriveTime;
    private Double startTime;
    private Double endTime;
    private Double queueTime;
    private Double processTime;
    private String eventType;
}
