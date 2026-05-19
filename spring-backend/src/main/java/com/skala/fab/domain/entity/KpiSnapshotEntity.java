package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "kpi_snapshot")
public class KpiSnapshotEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String runId;
    private Double snapshotTime;
    private String level;
    private String scope;
    private String kpiName;
    private Double value;
    private Integer windowMinutes;
    private Double numerator;
    private Double denominator;
    private String meta;
}
