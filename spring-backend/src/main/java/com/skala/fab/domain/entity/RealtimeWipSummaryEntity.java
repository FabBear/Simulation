package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "realtime_wip_summary")
public class RealtimeWipSummaryEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private Double snapshotTime;
    private String toolGroup;
    private String toolId;
    private Integer waitingLots;
    private Integer processingLots;
    private Double avgQueueTime;
}
